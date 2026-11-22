"""Promo codes: server-side discounts, limits that hold under a rush, safe money."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models.commerce import Booking
from app.models.user import User, UserRole, UserStatus
from app.schemas.booking import BookingCreateRequest, BookingItemRequest
from app.services.booking import BookingService
from app.services.inventory import InventoryService
from app.services.outbox import OutboxService
from tests.integration.conftest import customer_session, seed_admin, sign_in_as, unique_email
from tests.integration.google_stub import StubGoogleClient
from tests.integration.test_review_fixes import make_event, racing_sessions  # noqa: F401

pytestmark = pytest.mark.integration

PRICE = 100000  # make_event sells General at 1,000 rupees


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def service(session: AsyncSession) -> BookingService:
    settings = Settings(environment="test", secret_key="t" * 64)
    return BookingService(
        session,
        settings,
        InventoryService(session, settings.reservation_hold_seconds),
        OutboxService(session),
    )


async def customer(session: AsyncSession) -> User:
    user = User(
        role=UserRole.CUSTOMER,
        status=UserStatus.ACTIVE,
        email=unique_email("buyer"),
        phone_e164=f"+9190{uuid.uuid4().int % 10**8:08d}",
    )
    session.add(user)
    await session.flush()
    return user


async def code(session: AsyncSession, admin_token: str, api: AsyncClient, **body: object) -> dict:
    payload = {"code": f"T{uuid.uuid4().hex[:7]}", "discount_type": "PERCENT", "percent_off": 20}
    payload.update(body)
    response = await api.post("/api/v1/admin/promos", headers=bearer(admin_token), json=payload)
    assert response.status_code == 201, response.text
    return response.json()


async def book(session, user, slug, category_id, quantity=2, promo=None):  # type: ignore[no-untyped-def]
    return await service(session).create(
        BookingCreateRequest(
            event_slug=slug,
            items=[BookingItemRequest(ticket_category_id=category_id, quantity=quantity)],
            promo_code=promo,
        ),
        customer=user,
    )


async def test_a_percentage_and_a_fixed_code_discount_the_server_side_total(
    api: AsyncClient, db_session: AsyncSession, google: StubGoogleClient
) -> None:
    event, category = await make_event(db_session)
    slug, category_id = event.slug, category.id
    admin = await sign_in_as(api, google, await seed_admin(db_session))
    pct = await code(db_session, admin, api, discount_type="PERCENT", percent_off=20)
    fixed = await code(
        db_session, admin, api, discount_type="FIXED", percent_off=None, amount_off_paise=50000
    )

    buyer = await customer(db_session)
    booking, _ = await book(db_session, buyer, slug, category_id, 2, pct["code"].lower())
    assert (booking.subtotal_paise, booking.discount_paise, booking.total_paise) == (
        200000,
        40000,
        160000,
    )
    assert booking.status.value == "PENDING" and booking.promo_code_id is not None

    other = await customer(db_session)
    second, _ = await book(db_session, other, slug, category_id, 2, f" {fixed['code']} ")
    assert (second.discount_paise, second.total_paise) == (50000, 150000)

    used = (
        await db_session.execute(
            sa.text("SELECT code, used_count FROM promo_codes WHERE code = ANY(:c)"),
            {"c": [pct["code"], fixed["code"]]},
        )
    ).all()
    assert {r[1] for r in used} == {1}


async def test_a_code_worth_more_than_the_tickets_is_capped_and_a_free_booking_confirms_itself(
    api: AsyncClient, db_session: AsyncSession, google: StubGoogleClient
) -> None:
    event, category = await make_event(db_session)
    slug, category_id = event.slug, category.id
    admin = await sign_in_as(api, google, await seed_admin(db_session))
    everything = await code(db_session, admin, api, discount_type="PERCENT", percent_off=100)
    huge = await code(
        db_session, admin, api, discount_type="FIXED", percent_off=None, amount_off_paise=99_000_000
    )

    for promo in (everything, huge):
        buyer = await customer(db_session)
        booking, _ = await book(db_session, buyer, slug, category_id, 1, promo["code"])
        assert booking.subtotal_paise == PRICE and booking.discount_paise == PRICE
        assert booking.total_paise == 0  # never negative
        # Nothing to pay, so it is confirmed at once and the tickets are queued, with no gateway.
        assert booking.status.value == "CONFIRMED"
        queued = (
            await db_session.execute(
                sa.text("SELECT count(*) FROM outbox_messages WHERE dedup_key = :k"),
                {"k": f"booking.confirmed:{booking.id}"},
            )
        ).scalar_one()
        assert queued == 1
    sold = (
        await db_session.execute(
            sa.text("SELECT sold_count, reserved_count FROM ticket_categories WHERE id = :i"),
            {"i": category_id},
        )
    ).one()
    assert tuple(sold) == (2, 0)


async def test_the_database_itself_refuses_a_discount_that_breaks_the_total(
    db_session: AsyncSession,
) -> None:
    event, _ = await make_event(db_session)
    buyer = await customer(db_session)
    for discount, total in ((300000, 0), (50000, 200000), (-1, 200001)):
        db_session.add(
            Booking(
                reference=f"JIVE-{uuid.uuid4().hex[:8].upper()}",
                user_id=buyer.id,
                event_id=event.id,
                subtotal_paise=200000,
                fees_paise=0,
                discount_paise=discount,
                total_paise=total,
                quantity=2,
            )
        )
        with pytest.raises(IntegrityError):
            await db_session.flush()
        await db_session.rollback()


async def test_each_reason_a_code_is_refused_is_clear_and_gives_the_tickets_back(
    api: AsyncClient, db_session: AsyncSession, google: StubGoogleClient
) -> None:
    event, category = await make_event(db_session, capacity=10)
    other_event, _ = await make_event(db_session)
    slug, category_id, other_id = event.slug, category.id, other_event.id
    admin = await sign_in_as(api, google, await seed_admin(db_session))
    now = datetime.now(UTC)
    iso = lambda d: d.isoformat()  # noqa: E731
    cases = {
        "PROMO_INVALID": "NOPE",
        "PROMO_WRONG_EVENT": (await code(db_session, admin, api, event_id=str(other_id)))["code"],
        "PROMO_EXPIRED": (
            await code(
                db_session,
                admin,
                api,
                valid_from=iso(now - timedelta(days=3)),
                valid_until=iso(now - timedelta(days=1)),
            )
        )["code"],
        "PROMO_NOT_STARTED": (
            await code(db_session, admin, api, valid_from=iso(now + timedelta(days=2)))
        )["code"],
    }
    off = await code(db_session, admin, api)
    await api.patch(
        f"/api/v1/admin/promos/{off['id']}", headers=bearer(admin), json={"is_active": False}
    )
    cases["PROMO_INVALID_OFF"] = off["code"]

    buyer = await customer(db_session)
    for label, promo in cases.items():
        from app.core.errors import AppError

        with pytest.raises(AppError) as refused:
            await book(db_session, buyer, slug, category_id, 2, promo)
        expected = "PROMO_INVALID" if label.startswith("PROMO_INVALID") else label
        assert refused.value.code == expected, label

    # Refusals must not leave tickets held.
    held = (
        await db_session.execute(
            sa.text("SELECT reserved_count FROM ticket_categories WHERE id = :i"),
            {"i": category_id},
        )
    ).scalar_one()
    assert held == 0


async def test_once_per_customer_and_a_lapsed_booking_gives_its_use_back(
    api: AsyncClient, db_session: AsyncSession, google: StubGoogleClient
) -> None:
    from app.core.errors import AppError

    event, category = await make_event(db_session, capacity=10)
    slug, category_id = event.slug, category.id
    admin = await sign_in_as(api, google, await seed_admin(db_session))
    promo = await code(db_session, admin, api, max_uses=1)
    buyer = await customer(db_session)

    first, _ = await book(db_session, buyer, slug, category_id, 1, promo["code"])
    with pytest.raises(AppError) as again:
        await book(db_session, buyer, slug, category_id, 1, promo["code"])
    assert again.value.code == "PROMO_ALREADY_USED"

    rival = await customer(db_session)
    with pytest.raises(AppError) as gone:
        await book(db_session, rival, slug, category_id, 1, promo["code"])
    assert gone.value.code == "PROMO_EXHAUSTED"

    # The first booking is never paid and lapses: the use comes back, and someone else can have it.
    await service(db_session).expire(first)
    used = (
        await db_session.execute(
            sa.text("SELECT used_count FROM promo_codes WHERE id = :i"), {"i": promo["id"]}
        )
    ).scalar_one()
    assert used == 0
    taken, _ = await book(db_session, rival, slug, category_id, 1, promo["code"])
    assert taken.discount_paise > 0


async def test_a_limited_code_cannot_be_used_more_than_allowed_in_a_rush(
    racing_sessions,  # type: ignore[no-untyped-def]  # noqa: F811
) -> None:
    seed, make_session, created = racing_sessions
    _event_id, category_id, first_user, slug = await seed(capacity=50, limit=4)
    promo_id = uuid.uuid4()
    extra_users: list[uuid.UUID] = []
    try:
        async with make_session() as session:
            session.add(
                __import__("app.models.promo", fromlist=["PromoCode"]).PromoCode(
                    id=promo_id,
                    code=f"RUSH{uuid.uuid4().hex[:6].upper()}",
                    discount_type="PERCENT",
                    percent_off=10,
                    max_uses=1,
                    max_uses_per_customer=1,
                )
            )
            for _ in range(5):
                extra = User(
                    role=UserRole.CUSTOMER,
                    status=UserStatus.ACTIVE,
                    email=unique_email("rush"),
                    phone_e164=f"+9190{uuid.uuid4().int % 10**8:08d}",
                )
                session.add(extra)
                await session.flush()
                extra_users.append(extra.id)
            await session.commit()
            promo_code = (
                await session.execute(
                    sa.text("SELECT code FROM promo_codes WHERE id = :i"), {"i": promo_id}
                )
            ).scalar_one()

        async def attempt(user_id: uuid.UUID) -> str:
            async with make_session() as session:
                buyer = await session.get(User, user_id)
                try:
                    booking, _ = await book(session, buyer, slug, category_id, 1, promo_code)
                    return "got-it" if booking.discount_paise else "no-discount"
                except Exception as exc:
                    return getattr(exc, "code", type(exc).__name__)

        results = await asyncio.gather(*(attempt(u) for u in extra_users))
        assert results.count("got-it") == 1, results
        assert results.count("PROMO_EXHAUSTED") == 4, results
        async with make_session() as session:
            used = (
                await session.execute(
                    sa.text("SELECT used_count FROM promo_codes WHERE id = :i"), {"i": promo_id}
                )
            ).scalar_one()
        assert used == 1
    finally:
        async with make_session() as session:
            await session.execute(
                sa.text("DELETE FROM ticket_reservations WHERE event_id = :e"),
                {"e": created["event"]},
            )
            await session.execute(
                sa.text(
                    "DELETE FROM booking_items WHERE booking_id IN "
                    "(SELECT id FROM bookings WHERE event_id = :e)"
                ),
                {"e": created["event"]},
            )
            await session.execute(
                sa.text("DELETE FROM bookings WHERE event_id = :e"), {"e": created["event"]}
            )
            await session.execute(sa.text("DELETE FROM promo_codes WHERE id = :i"), {"i": promo_id})
            if extra_users:
                await session.execute(
                    sa.text("DELETE FROM users WHERE id = ANY(:u)"), {"u": extra_users}
                )
            await session.commit()
        _ = first_user


async def test_wrong_guesses_are_throttled(db_session: AsyncSession) -> None:
    from app.core.errors import AppError, RateLimitedError

    event, category = await make_event(db_session, capacity=10)
    slug, category_id = event.slug, category.id
    buyer = await customer(db_session)
    seen_limit = False
    for _ in range(14):
        try:
            await book(db_session, buyer, slug, category_id, 1, "GUESS" + uuid.uuid4().hex[:4])
        except RateLimitedError:
            seen_limit = True
            break
        except AppError:
            continue
    assert seen_limit


async def test_the_check_endpoint_matches_the_booking_and_changes_nothing(
    api: AsyncClient, db_session: AsyncSession, google: StubGoogleClient
) -> None:
    event, category = await make_event(db_session, capacity=10)
    slug, category_id = event.slug, category.id
    admin = await sign_in_as(api, google, await seed_admin(db_session))
    promo = await code(db_session, admin, api, percent_off=25)
    session_ = await customer_session(api, google)
    body = {
        "event_slug": slug,
        "code": promo["code"].lower(),
        "items": [{"ticket_category_id": str(category_id), "quantity": 3}],
    }
    assert (await api.post("/api/v1/bookings/promo-check", json=body)).status_code == 401
    checked = await api.post(
        "/api/v1/bookings/promo-check", headers=bearer(session_["access"]), json=body
    )
    assert checked.status_code == 200, checked.text
    assert checked.json() == {
        "code": promo["code"],
        "subtotal_paise": 300000,
        "discount_paise": 75000,
        "total_paise": 225000,
        "description": None,
    }
    untouched = (
        await db_session.execute(
            sa.text("SELECT used_count FROM promo_codes WHERE id = :i"), {"i": promo["id"]}
        )
    ).scalar_one()
    assert untouched == 0
    bad = await api.post(
        "/api/v1/bookings/promo-check",
        headers=bearer(session_["access"]),
        json={**body, "code": "NOPE"},
    )
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "PROMO_INVALID"


async def test_admin_rules_for_creating_editing_and_deleting_codes(
    api: AsyncClient, db_session: AsyncSession, google: StubGoogleClient
) -> None:
    event, category = await make_event(db_session)
    slug, category_id = event.slug, category.id
    customer_account = await customer_session(api, google)
    url = "/api/v1/admin/promos"
    assert (await api.get(url)).status_code == 401
    assert (await api.get(url, headers=bearer(customer_account["access"]))).status_code == 403

    admin = await sign_in_as(api, google, await seed_admin(db_session))
    h = bearer(admin)
    for bad in (
        {"code": "ab", "discount_type": "PERCENT", "percent_off": 10},
        {"code": "OK123", "discount_type": "PERCENT", "percent_off": 0},
        {"code": "OK123", "discount_type": "PERCENT", "percent_off": 101},
        {"code": "OK123", "discount_type": "PERCENT"},
        {"code": "OK123", "discount_type": "FIXED", "percent_off": 10},
        {"code": "OK123", "discount_type": "FIXED", "amount_off_paise": 0},
        {"code": "has space!", "discount_type": "PERCENT", "percent_off": 10},
    ):
        assert (await api.post(url, headers=h, json=bad)).status_code == 422, bad

    made = await code(db_session, admin, api, code="spring 2027")
    assert made["code"] == "SPRING2027"  # upper-cased, spaces removed
    duplicate = await api.post(
        url, headers=h, json={"code": "spring2027", "discount_type": "PERCENT", "percent_off": 5}
    )
    assert duplicate.status_code == 409

    # An unused code can be deleted; a used one cannot, it can only be switched off.
    assert (await api.delete(f"{url}/{made['id']}", headers=h)).status_code == 204
    used = await code(db_session, admin, api, max_uses=5)
    buyer = await customer(db_session)
    await book(db_session, buyer, slug, category_id, 1, used["code"])
    assert (await api.delete(f"{url}/{used['id']}", headers=h)).status_code == 409
    low = await api.patch(f"{url}/{used['id']}", headers=h, json={"max_uses": 1})
    assert low.status_code == 200
    below = await api.patch(f"{url}/{used['id']}", headers=h, json={"max_uses": 1})
    assert below.status_code == 200  # equal to what is used is allowed
    listed = (await api.get(url, headers=h)).json()
    assert used["code"] in [c["code"] for c in listed["items"]]
