"""The waitlist: join only when sold out, tell people in order when tickets return."""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.outbox import OutboxService
from app.services.waitlist import WaitlistService
from tests.integration.conftest import customer_session, seed_admin, sign_in_as, unique_email
from tests.integration.google_stub import StubGoogleClient
from tests.integration.test_review_fixes import make_event

pytestmark = pytest.mark.integration


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _sell_out(session: AsyncSession, category_id: object) -> None:
    await session.execute(
        sa.text("UPDATE ticket_categories SET sold_count = capacity WHERE id = :i"),
        {"i": category_id},
    )
    await session.commit()
    session.expire_all()


async def test_you_can_only_join_while_the_tickets_are_gone(
    api: AsyncClient, db_session: AsyncSession
) -> None:
    event, category = await make_event(db_session, capacity=3)
    slug, category_id = event.slug, category.id
    await db_session.commit()
    url = f"/api/v1/events/{slug}/waitlist"
    body = {"email": unique_email("w"), "quantity": 2}

    # Tickets exist: told to just book.
    open_sale = await api.post(url, json=body)
    assert open_sale.status_code == 409 and open_sale.json()["error"]["code"] == "TICKETS_AVAILABLE"

    await _sell_out(db_session, category_id)
    joined = await api.post(url, json=body)
    assert joined.status_code == 201 and joined.json() == {"ok": True}
    again = await api.post(url, json={**body, "email": body["email"].upper(), "quantity": 3})
    assert again.status_code == 201  # same person: updated, not duplicated
    rows = (
        await db_session.execute(
            sa.text("SELECT count(*), max(quantity) FROM waitlist_entries WHERE email = :e"),
            {"e": body["email"].lower()},
        )
    ).one()
    assert tuple(rows) == (1, 3)

    for bad in (
        (url, {**body, "email": "nope"}),
        (url, {**body, "quantity": 9}),
        (url, {**body, "ticket_category_id": "00000000-0000-0000-0000-000000000000"}),
        ("/api/v1/events/no-such-event/waitlist", body),
    ):
        assert (await api.post(bad[0], json=bad[1])).status_code in (404, 422)

    bot = unique_email("bot")
    assert (await api.post(url, json={"email": bot, "website": "http://spam"})).status_code == 201
    stored = (
        await db_session.execute(
            sa.text("SELECT count(*) FROM waitlist_entries WHERE email = :e"), {"e": bot.lower()}
        )
    ).scalar_one()
    assert stored == 0


async def test_people_are_told_in_order_only_once_and_only_when_tickets_return(
    api: AsyncClient, db_session: AsyncSession
) -> None:
    event, category = await make_event(db_session, capacity=2)
    slug, category_id = event.slug, category.id
    await db_session.commit()
    await _sell_out(db_session, category_id)
    url = f"/api/v1/events/{slug}/waitlist"
    people = [unique_email(f"p{i}") for i in range(6)]
    for person in people:
        assert (await api.post(url, json={"email": person})).status_code == 201

    service = WaitlistService(db_session, OutboxService(db_session))
    # Still sold out: nobody is told.
    assert await service.notify_available() == 0

    # One ticket comes back. With the buffer, the first two people in line are told.
    await db_session.execute(
        sa.text("UPDATE ticket_categories SET sold_count = capacity - 1 WHERE id = :i"),
        {"i": category_id},
    )
    await db_session.commit()
    db_session.expire_all()
    assert await service.notify_available() == 2

    status = dict(
        (
            await db_session.execute(
                sa.text(
                    "SELECT email, status FROM waitlist_entries "
                    "WHERE email = ANY(:e) ORDER BY created_at"
                ),
                {"e": [p.lower() for p in people]},
            )
        ).all()
    )
    assert [status[p.lower()] for p in people] == ["NOTIFIED"] * 2 + ["WAITING"] * 4
    queued = (
        await db_session.execute(
            sa.text("SELECT count(*) FROM outbox_messages WHERE topic = 'waitlist.available'")
        )
    ).scalar_one()
    assert queued >= 2

    # A second look finds nothing new to say: the two people told still count against the one
    # ticket, so the rest of the list is not emailed about it.
    assert await service.notify_available() == 0

    # More tickets coming back widens the circle, but does not repeat anyone.
    await db_session.execute(
        sa.text("UPDATE ticket_categories SET sold_count = 0 WHERE id = :i"), {"i": category_id}
    )
    await db_session.commit()
    db_session.expire_all()
    assert await service.notify_available() == 2  # 2 free x 2 buffer = 4, minus 2 already told


async def test_a_waitlist_for_one_ticket_type_ignores_other_types(
    api: AsyncClient, db_session: AsyncSession
) -> None:
    event, general = await make_event(db_session, capacity=1)
    slug, general_id, event_id = event.slug, general.id, event.id
    await db_session.execute(
        sa.text(
            "INSERT INTO ticket_categories (id, event_id, name, price_paise, capacity, "
            "max_per_booking, currency, sold_count, reserved_count, min_per_booking, "
            "sort_order, is_active) VALUES (gen_random_uuid(), :e, 'VIP', 500000, 5, 5, "
            "'INR', 0, 0, 1, 1, true)"
        ),
        {"e": event_id},
    )
    await db_session.commit()
    await _sell_out(db_session, general_id)
    waiting_for_general = unique_email("gen")
    r = await api.post(
        f"/api/v1/events/{slug}/waitlist",
        json={"email": waiting_for_general, "ticket_category_id": str(general_id)},
    )
    assert r.status_code == 201

    # VIP has seats, General does not: the General-only person is not told.
    service = WaitlistService(db_session, OutboxService(db_session))
    assert await service.notify_available() == 0
    # "Any type" would have been refused to join, since VIP is open.
    anyone = await api.post(f"/api/v1/events/{slug}/waitlist", json={"email": unique_email("any")})
    assert anyone.status_code == 409


async def test_leaving_and_the_admin_list(
    api: AsyncClient, db_session: AsyncSession, google: StubGoogleClient
) -> None:
    event, category = await make_event(db_session, capacity=1)
    slug, category_id, event_id = event.slug, category.id, event.id
    await db_session.commit()
    await _sell_out(db_session, category_id)
    stays, leaves = unique_email("stay"), unique_email("leave")
    for email in (stays, leaves):
        await api.post(f"/api/v1/events/{slug}/waitlist", json={"email": email})
    token = (
        await db_session.execute(
            sa.text("SELECT leave_token FROM waitlist_entries WHERE email = :e"),
            {"e": leaves.lower()},
        )
    ).scalar_one()
    assert (await api.post("/api/v1/waitlist/leave", json={"token": "x" * 30})).status_code == 200
    assert (await api.post("/api/v1/waitlist/leave", json={"token": token})).status_code == 200

    admin = await sign_in_as(api, google, await seed_admin(db_session))
    page = (
        await api.get(f"/api/v1/admin/events/{event_id}/waitlist", headers=bearer(admin))
    ).json()
    assert page["waiting"] == 1 and page["total"] == 1
    assert [r["email"] for r in page["items"]] == [stays.lower()]

    customer = await customer_session(api, google)
    forbidden = await api.get(
        f"/api/v1/admin/events/{event_id}/waitlist", headers=bearer(customer["access"])
    )
    assert forbidden.status_code == 403
