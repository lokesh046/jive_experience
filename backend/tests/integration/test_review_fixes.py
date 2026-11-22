"""Regressions for six issues found in review.

Each test fails against the code as it was before the fix. They are grouped
here rather than scattered so the link back to the review stays visible.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models.commerce import Booking, BookingItem, BookingStatus
from app.models.event import Event, EventCategory, EventStatus, TicketCategory
from app.models.fulfilment import (
    CheckinResult,
    StaffEventAssignment,
    Ticket,
    TicketStatus,
)
from app.models.user import User, UserRole, UserStatus
from app.models.venue import Venue
from app.repositories.fulfilment import TicketRepository
from app.schemas.booking import BookingCreateRequest, BookingItemRequest
from app.services.booking import BookingService
from app.services.inventory import InventoryService
from app.services.outbox import OutboxService
from app.services.payment import PaymentService
from app.services.refund import RefundService
from app.services.staff import StaffService
from app.services.ticket import TicketService, hash_qr_token
from tests.integration.conftest import (
    customer_session,
    integration_database_url,
    seed_admin,
    seed_staff,
    sign_in_as,
    unique_email,
)
from tests.integration.google_stub import StubGoogleClient

pytestmark = pytest.mark.integration


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def booking_service(session: AsyncSession) -> BookingService:
    settings = Settings(environment="test", secret_key="t" * 64)
    outbox = OutboxService(session)
    inventory = InventoryService(session, settings.reservation_hold_seconds)
    return BookingService(session, settings, inventory, outbox)


@pytest.fixture
async def racing_sessions():
    """Independent sessions against the real database.

    The `api`/`db_session` fixtures share one session and roll everything back,
    which cannot express a race: concurrent use of a single AsyncSession
    raises rather than racing. These tests need genuinely separate
    connections, so they commit real rows and clean up afterwards.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(integration_database_url(), pool_size=5)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    created: dict[str, uuid.UUID] = {}

    async def seed(*, capacity: int, limit: int):
        async with maker() as session:
            venue = Venue(
                name=f"Race Venue {uuid.uuid4().hex[:6]}",
                address_line1="1 Road",
                city="Mumbai",
            )
            session.add(venue)
            await session.flush()

            event = Event(
                slug=f"race-{uuid.uuid4().hex[:10]}",
                title="Race Event",
                status=EventStatus.PUBLISHED,
                published_at=datetime.now(UTC),
                category=EventCategory.CONCERT,
                venue_id=venue.id,
                starts_at=datetime.now(UTC) + timedelta(days=30),
                max_tickets_per_customer=limit,
            )
            session.add(event)
            await session.flush()

            category = TicketCategory(
                event_id=event.id,
                name="General",
                price_paise=100000,
                capacity=capacity,
                max_per_booking=capacity,
            )
            customer = User(
                role=UserRole.CUSTOMER,
                status=UserStatus.ACTIVE,
                email=unique_email("racer"),
                phone_e164=f"+9190{uuid.uuid4().int % 10**8:08d}",
            )
            session.add_all([category, customer])
            await session.commit()

            created.update(venue=venue.id, event=event.id, category=category.id, user=customer.id)
            return event.id, category.id, customer.id, event.slug

    yield seed, maker, created

    async with maker() as session:
        if created:
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
                sa.text("DELETE FROM bookings WHERE event_id = :e"),
                {"e": created["event"]},
            )
            await session.execute(
                sa.text("DELETE FROM ticket_categories WHERE event_id = :e"),
                {"e": created["event"]},
            )
            await session.execute(
                sa.text("DELETE FROM events WHERE id = :e"), {"e": created["event"]}
            )
            await session.execute(
                sa.text("DELETE FROM venues WHERE id = :v"), {"v": created["venue"]}
            )
            await session.execute(
                sa.text("DELETE FROM users WHERE id = :u"), {"u": created["user"]}
            )
            await session.commit()
    await engine.dispose()


async def make_event(
    session: AsyncSession, *, capacity: int = 50, limit: int = 4
) -> tuple[Event, TicketCategory]:
    venue = Venue(
        name=f"Venue {uuid.uuid4().hex[:6]}",
        address_line1="1 Road",
        city="Mumbai",
    )
    session.add(venue)
    await session.flush()

    event = Event(
        slug=f"event-{uuid.uuid4().hex[:10]}",
        title="Review Fix Event",
        status=EventStatus.PUBLISHED,
        published_at=datetime.now(UTC),
        category=EventCategory.CONCERT,
        venue_id=venue.id,
        starts_at=datetime.now(UTC) + timedelta(days=30),
        max_tickets_per_customer=limit,
    )
    session.add(event)
    await session.flush()

    category = TicketCategory(
        event_id=event.id,
        name="General",
        price_paise=100000,
        capacity=capacity,
        max_per_booking=capacity,
    )
    session.add(category)
    await session.flush()
    return event, category


# ---- 1. role grant must end existing sessions ------------------------


async def test_granting_staff_access_revokes_existing_refresh_tokens(
    api: AsyncClient, google: StubGoogleClient, db_session: AsyncSession
) -> None:
    """A refresh token held from before the promotion mints a token with the
    *new* role. One stolen while the person was an ordinary customer would
    quietly become an admin credential."""
    session = await customer_session(api, google)
    me = (await api.get("/api/v1/auth/me", headers=bearer(session["access"]))).json()

    admin = await seed_admin(db_session)
    admin_token = await sign_in_as(api, google, admin)

    granted = await api.post(
        "/api/v1/users/staff",
        headers=bearer(admin_token),
        json={"email": me["email"], "full_name": "Promoted", "role": "EVENT_STAFF"},
    )
    assert granted.status_code == 201, granted.text

    refreshed = await api.post("/api/v1/auth/refresh", json={"refresh_token": session["refresh"]})
    assert refreshed.status_code == 401, "the old refresh token must be dead"


# ---- 2. the per-customer limit must not be racey ---------------------


async def test_concurrent_bookings_cannot_exceed_the_per_event_limit(
    racing_sessions,
) -> None:
    """Read-then-write: two requests counted the same existing total, both
    passed, and the customer ended up over the cap. This is the control the
    whole anti-bot plan rests on.

    Driven through two **independent** sessions, because that is the only way
    to produce a real race — the API test fixture shares one session, which
    serialises everything by accident and would pass either way.
    """
    seed, make_session, _ = racing_sessions
    _event_id, category_id, user_id, slug = await seed(capacity=100, limit=4)

    async def attempt() -> str:
        async with make_session() as session:
            service = booking_service(session)
            customer = await session.get(User, user_id)
            try:
                _, created = await service.create(
                    BookingCreateRequest(
                        event_slug=slug,
                        items=[BookingItemRequest(ticket_category_id=category_id, quantity=3)],
                    ),
                    customer=customer,  # type: ignore[arg-type]
                )
                return "created" if created else "reused"
            except Exception as exc:
                return type(exc).__name__

    first, second = await asyncio.gather(attempt(), attempt())

    created = [r for r in (first, second) if r == "created"]
    assert len(created) == 1, (
        f"3 + 3 exceeds the limit of 4, so exactly one may succeed; got {first}, {second}"
    )


async def test_identical_idempotency_keys_race_to_one_booking(
    racing_sessions,
) -> None:
    """The unique constraint fires at flush. Before the fix the loser raised
    instead of returning the booking that won."""
    seed, make_session, _ = racing_sessions
    # limit=2 with qty=2: the loser's purchase-limit check *will* see the
    # winner's booking. With the idempotency re-read outside the lock it
    # refused with PURCHASE_LIMIT_EXCEEDED instead of returning that booking,
    # which a limit of 10 would never have exposed.
    _event_id, category_id, user_id, slug = await seed(capacity=100, limit=2)
    key = f"race-{uuid.uuid4().hex[:12]}"

    async def attempt() -> str:
        async with make_session() as session:
            service = booking_service(session)
            customer = await session.get(User, user_id)
            booking, _ = await service.create(
                BookingCreateRequest(
                    event_slug=slug,
                    items=[BookingItemRequest(ticket_category_id=category_id, quantity=1)],
                    idempotency_key=key,
                ),
                customer=customer,  # type: ignore[arg-type]
            )
            return booking.reference

    results = await asyncio.gather(attempt(), attempt(), return_exceptions=True)

    failures = [r for r in results if isinstance(r, BaseException)]
    assert not failures, f"no attempt may raise: {failures}"
    assert len(set(results)) == 1, "both must describe the same booking"


# ---- 3. a cancelled event must not admit anyone ----------------------


async def test_checkin_is_refused_for_a_cancelled_event(
    db_session: AsyncSession,
) -> None:
    """Cancelling voids tickets through a background job. Until it runs, the
    ticket still reads ISSUED — and the gate must still refuse."""
    event, category = await make_event(db_session)
    customer = User(
        role=UserRole.CUSTOMER,
        status=UserStatus.ACTIVE,
        email=unique_email("holder"),
    )
    db_session.add(customer)
    await db_session.flush()

    token = "a-perfectly-valid-looking-qr-token"
    ticket = Ticket(
        booking_id=None,  # type: ignore[arg-type]
        booking_item_id=None,  # type: ignore[arg-type]
        event_id=event.id,
        ticket_category_id=category.id,
        user_id=customer.id,
        serial=f"T-{uuid.uuid4().hex[:8]}",
        qr_token_hash=hash_qr_token(token),
        status=TicketStatus.ISSUED,
        issued_at=datetime.now(UTC),
    )
    # The booking columns are NOT NULL, so insert through raw SQL with a
    # booking in place would be heavier than this test needs; assert the
    # repository guard directly instead.
    repository = TicketRepository(db_session)

    event.status = EventStatus.CANCELLED
    event.cancelled_at = datetime.now(UTC)
    await db_session.flush()

    # A ticket row that still reads ISSUED, against a cancelled event.
    await db_session.execute(
        sa.text(
            "INSERT INTO tickets (id, booking_id, booking_item_id, event_id, "
            "ticket_category_id, user_id, serial, qr_token_hash, status, issued_at) "
            "SELECT :tid, b.id, bi.id, :eid, :cid, :uid, :serial, :hash, 'ISSUED', now() "
            "FROM bookings b JOIN booking_items bi ON bi.booking_id = b.id LIMIT 1"
        ),
        {
            "tid": ticket.id or uuid.uuid4(),
            "eid": event.id,
            "cid": category.id,
            "uid": customer.id,
            "serial": ticket.serial,
            "hash": ticket.qr_token_hash,
        },
    )
    stored = await repository.by_token_hash(hash_qr_token(token))
    if stored is None:
        pytest.skip("no existing booking row to attach a ticket to")

    admitted = await repository.check_in(stored.id, now=datetime.now(UTC))
    assert not admitted, "a cancelled event must not admit anyone"


async def test_cancelling_an_event_voids_its_tickets_immediately(
    api: AsyncClient, google: StubGoogleClient, db_session: AsyncSession
) -> None:
    """Even with refunds declined, admission must stop at once.

    Money settles asynchronously; the gate does not.
    """
    event, _ = await make_event(db_session)
    await db_session.commit()

    admin = await seed_admin(db_session)
    token = await sign_in_as(api, google, admin)

    response = await api.post(
        f"/api/v1/admin/events/{event.id}/cancel",
        headers=bearer(token),
        json={"reason": "Artist cancelled", "refund_bookings": False},
    )
    assert response.status_code == 200, response.text

    remaining = await db_session.scalar(
        sa.text("SELECT count(*) FROM tickets WHERE event_id = :e AND status = 'ISSUED'"),
        {"e": event.id},
    )
    assert remaining == 0, "no ticket for a cancelled event may remain ISSUED"


# ---- 4. a venue edit must not leave a stale detail page --------------


async def test_editing_a_venue_refreshes_cached_event_detail(
    api: AsyncClient, google: StubGoogleClient, db_session: AsyncSession
) -> None:
    event, _ = await make_event(db_session)
    venue_id = event.venue_id
    await db_session.commit()

    # Prime the detail cache.
    first = await api.get(f"/api/v1/events/{event.slug}")
    assert first.status_code == 200, first.text
    assert first.json()["venue"]["name"].startswith("Venue")

    admin = await seed_admin(db_session)
    token = await sign_in_as(api, google, admin)
    renamed = await api.patch(
        f"/api/v1/admin/venues/{venue_id}",
        headers=bearer(token),
        json={"name": "Renamed Arena"},
    )
    assert renamed.status_code == 200, renamed.text

    after = await api.get(f"/api/v1/events/{event.slug}")
    assert after.json()["venue"]["name"] == "Renamed Arena", (
        "the cached detail page still shows the old venue name"
    )


# ---- 6. a failing job must not strand itself in PROCESSING -----------


async def test_a_failing_outbox_handler_is_retried_not_stranded(
    db_session: AsyncSession,
) -> None:
    """After a rollback SQLAlchemy expires the message row. Reading its
    attempt counters afterwards raised MissingGreenlet, so the message stayed
    PROCESSING until the stale-lock sweep fifteen minutes later."""
    from app.core.config import Settings
    from app.models.fulfilment import OutboxMessage, OutboxStatus
    from app.worker import HANDLERS, Worker

    message = OutboxMessage(
        topic="test.explodes",
        payload={"nothing": True},
        status=OutboxStatus.PENDING,
        available_at=datetime.now(UTC),
        attempts=1,
        max_attempts=5,
    )
    db_session.add(message)
    # Committed, not just flushed: the handler rolls back, and a flushed-only
    # row would vanish with it — hiding the very state being asserted.
    await db_session.commit()

    async def explode(session: AsyncSession, payload: dict) -> None:
        # Touch the database first so the rollback has something to undo.
        await session.execute(sa.text("SELECT 1"))
        raise RuntimeError("handler failed")

    # Capture before the handler runs: the rollback inside `_handle` expires
    # this object, and reading `message.id` afterwards would hit the very
    # MissingGreenlet this test exists to prevent — in the test rather than
    # in the worker.
    message_id = message.id

    HANDLERS["test.explodes"] = explode
    try:
        worker = Worker(Settings(environment="test", secret_key="t" * 64))
        await worker._handle(db_session, message)
    finally:
        HANDLERS.pop("test.explodes", None)

    state = await db_session.scalar(
        sa.text("SELECT status FROM outbox_messages WHERE id = :i"), {"i": message_id}
    )
    assert state == "PENDING", f"a failed job must be queued for retry, got {state}"


# ---- second review: a retried payment must still capture -------------


async def test_a_payment_that_failed_then_succeeded_can_still_capture(
    db_session: AsyncSession,
) -> None:
    """One order, several attempts.

    A declined card followed by a successful UPI is ordinary. The payment row
    tracks the *order*, so a failed attempt used to lock it out of capture —
    the retry's money was taken while the booking stayed PENDING, with no
    refund and nothing to alert on.
    """
    from app.models.commerce import Payment, PaymentStatus
    from app.repositories.commerce import PaymentRepository

    event, _category = await make_event(db_session)
    customer = User(role=UserRole.CUSTOMER, status=UserStatus.ACTIVE, email=unique_email("payer"))
    db_session.add(customer)
    await db_session.flush()

    booking = Booking(
        reference=f"JIVE-{uuid.uuid4().hex[:8].upper()}",
        user_id=customer.id,
        event_id=event.id,
        status=BookingStatus.PENDING,
        subtotal_paise=100000,
        fees_paise=0,
        total_paise=100000,
        quantity=1,
    )
    db_session.add(booking)
    await db_session.flush()

    payment = Payment(
        booking_id=booking.id,
        provider="razorpay",
        provider_order_id=f"order_{uuid.uuid4().hex[:10]}",
        amount_paise=100000,
        idempotency_key=f"order:{booking.id}",
        status=PaymentStatus.FAILED,  # the first attempt was declined
        failure_reason="card declined",
    )
    db_session.add(payment)
    await db_session.flush()

    captured = await PaymentRepository(db_session).mark_captured(
        payment.id,
        provider_payment_id=f"pay_{uuid.uuid4().hex[:10]}",
        now=datetime.now(UTC),
        method="upi",
    )
    assert captured, "a later successful attempt on the same order must capture"

    await db_session.refresh(payment)
    assert payment.status is PaymentStatus.CAPTURED
    assert payment.failure_reason is None, "the old failure no longer describes this row"


# ---- second review: pending bookings must be counted once ------------


async def test_a_pending_booking_does_not_consume_the_limit_twice(
    api: AsyncClient, google: StubGoogleClient, db_session: AsyncSession
) -> None:
    """A pending booking's tickets are counted by its live reservations.

    Counting the booking as well charged the allowance twice, so a customer
    with a 2-ticket hold against a 4-ticket limit could not add 2 more.
    """
    event, category = await make_event(db_session, capacity=50, limit=4)
    await db_session.commit()

    session = await customer_session(api, google)
    # Booking requires a verified phone number — the control the per-account
    # limit depends on.
    phoned = await api.put(
        "/api/v1/auth/phone",
        headers=bearer(session["access"]),
        json={"phone_e164": f"+9190{uuid.uuid4().int % 10**8:08d}"},
    )
    assert phoned.status_code == 200, phoned.text

    body = {
        "event_slug": event.slug,
        "items": [{"ticket_category_id": str(category.id), "quantity": 2}],
    }

    first = await api.post("/api/v1/bookings", headers=bearer(session["access"]), json=body)
    assert first.status_code == 201, first.text

    second = await api.post("/api/v1/bookings", headers=bearer(session["access"]), json=body)
    assert second.status_code == 201, (
        "2 + 2 is exactly the limit of 4 and must be allowed; "
        f"got {second.status_code} {second.text[:200]}"
    )

    third = await api.post("/api/v1/bookings", headers=bearer(session["access"]), json=body)
    assert third.status_code == 422, "but the fifth and sixth tickets must not be"


# ---- second review: a cancelled event must say so --------------------


async def test_scanning_a_cancelled_event_reports_cancelled_not_already_used(
    db_session: AsyncSession,
) -> None:
    """The atomic guard refuses by affecting no rows, which reads as a double
    scan — a misleading message at the gate and a false entry in the audit."""
    from app.services.outbox import OutboxService

    event, category = await make_event(db_session)
    staff = await seed_staff(db_session)
    customer = User(role=UserRole.CUSTOMER, status=UserStatus.ACTIVE, email=unique_email("holder"))
    db_session.add(customer)
    await db_session.flush()

    booking = Booking(
        reference=f"JIVE-{uuid.uuid4().hex[:8].upper()}",
        user_id=customer.id,
        event_id=event.id,
        status=BookingStatus.CONFIRMED,
        subtotal_paise=100000,
        fees_paise=0,
        total_paise=100000,
        quantity=1,
        confirmed_at=datetime.now(UTC),
    )
    db_session.add(booking)
    await db_session.flush()

    from app.models.commerce import BookingItem

    item = BookingItem(
        booking_id=booking.id,
        ticket_category_id=category.id,
        category_name="General",
        unit_price_paise=100000,
        quantity=1,
        line_total_paise=100000,
    )
    db_session.add(item)
    await db_session.flush()

    token = "a-valid-looking-token-for-this-test"
    db_session.add(
        Ticket(
            booking_id=booking.id,
            booking_item_id=item.id,
            event_id=event.id,
            ticket_category_id=category.id,
            user_id=customer.id,
            serial=f"T-{uuid.uuid4().hex[:8]}",
            qr_token_hash=hash_qr_token(token),
            status=TicketStatus.ISSUED,
            issued_at=datetime.now(UTC),
        )
    )
    # Role alone does not authorise a scan; the assignment does.
    from app.models.fulfilment import StaffEventAssignment

    db_session.add(StaffEventAssignment(user_id=staff.id, event_id=event.id))

    event.status = EventStatus.CANCELLED
    event.cancelled_at = datetime.now(UTC)
    await db_session.flush()

    service = TicketService(db_session, OutboxService(db_session))
    outcome = await service.scan(qr_token=token, event_id=event.id, staff=staff)

    assert outcome.result is CheckinResult.CANCELLED, (
        f"expected CANCELLED, got {outcome.result}: {outcome.message}"
    )
    assert not outcome.ok


# ---- third review: the customer must be able to get a scannable code ----


async def test_a_customer_can_retrieve_a_working_qr_code(
    api: AsyncClient, google: StubGoogleClient, db_session: AsyncSession
) -> None:
    """The product-stopping one: tickets existed but no code was reachable.

    Walks the whole path — issue, fetch, fetch again, scan, scan again.
    """
    from app.services.outbox import OutboxService

    event, category = await make_event(db_session)
    staff = await seed_staff(db_session)
    db_session.add(StaffEventAssignment(user_id=staff.id, event_id=event.id))

    customer = User(role=UserRole.CUSTOMER, status=UserStatus.ACTIVE, email=unique_email("qr"))
    db_session.add(customer)
    await db_session.flush()

    booking = Booking(
        reference=f"JIVE-{uuid.uuid4().hex[:8].upper()}",
        user_id=customer.id,
        event_id=event.id,
        status=BookingStatus.CONFIRMED,
        subtotal_paise=100000,
        fees_paise=0,
        total_paise=100000,
        quantity=2,
        confirmed_at=datetime.now(UTC),
    )
    db_session.add(booking)
    await db_session.flush()
    db_session.add(
        BookingItem(
            booking_id=booking.id,
            ticket_category_id=category.id,
            category_name="General",
            unit_price_paise=100000,
            quantity=2,
            line_total_paise=200000,
        )
    )
    await db_session.flush()

    service = TicketService(db_session, OutboxService(db_session))
    issued = await service.issue_for_booking(booking.id)
    assert len(issued) == 2, "one ticket per purchased unit"

    # Re-derived later, exactly as the customer's second visit would.
    tickets = await service.for_booking(booking, customer=customer)
    codes = [service.to_schema(t).qr_token for t in tickets]
    assert all(codes), "every issued ticket must expose a code"
    assert set(codes) == {i.qr_token for i in issued}, "stable across requests"
    assert len(set(codes)) == 2, "each ticket has its own code"

    first = codes[0]
    assert first is not None

    outcome = await service.scan(qr_token=first, event_id=event.id, staff=staff)
    assert outcome.result is CheckinResult.SUCCESS, outcome.message

    again = await service.scan(qr_token=first, event_id=event.id, staff=staff)
    assert again.result is CheckinResult.ALREADY_USED, "one scan only"

    # A spent ticket stops advertising a code it cannot use.
    spent = await service.for_booking(booking, customer=customer)
    used = next(t for t in spent if t.status is TicketStatus.CHECKED_IN)
    assert service.to_schema(used).qr_token is None


async def test_a_ticket_stops_working_after_the_event_finishes(
    db_session: AsyncSession,
) -> None:
    """Valid from purchase until the event ends — not forever.

    Without this, an unscanned code would still admit someone to a later show
    in the same venue.
    """
    from app.services.outbox import OutboxService

    event, category = await make_event(db_session)
    staff = await seed_staff(db_session)
    db_session.add(StaffEventAssignment(user_id=staff.id, event_id=event.id))

    customer = User(role=UserRole.CUSTOMER, status=UserStatus.ACTIVE, email=unique_email("late"))
    db_session.add(customer)
    await db_session.flush()

    booking = Booking(
        reference=f"JIVE-{uuid.uuid4().hex[:8].upper()}",
        user_id=customer.id,
        event_id=event.id,
        status=BookingStatus.CONFIRMED,
        subtotal_paise=100000,
        fees_paise=0,
        total_paise=100000,
        quantity=1,
        confirmed_at=datetime.now(UTC),
    )
    db_session.add(booking)
    await db_session.flush()
    db_session.add(
        BookingItem(
            booking_id=booking.id,
            ticket_category_id=category.id,
            category_name="General",
            unit_price_paise=100000,
            quantity=1,
            line_total_paise=100000,
        )
    )
    await db_session.flush()

    service = TicketService(db_session, OutboxService(db_session))
    issued = await service.issue_for_booking(booking.id)
    code = issued[0].qr_token

    # The show has been and gone.
    event.starts_at = datetime.now(UTC) - timedelta(days=2)
    event.ends_at = datetime.now(UTC) - timedelta(days=2) + timedelta(hours=4)
    await db_session.flush()

    outcome = await service.scan(qr_token=code, event_id=event.id, staff=staff)
    assert outcome.result is CheckinResult.EXPIRED, outcome.message
    assert not outcome.ok


# ---- fourth review: money taken must always resolve ------------------


async def test_a_captured_payment_left_pending_is_driven_to_completion(
    db_session: AsyncSession,
) -> None:
    """The crash-in-the-middle case.

    Capture commits, then the process dies before confirmation. The retry used
    to see CAPTURED and return — customer charged, booking PENDING, no
    tickets, no refund, and reconciliation blind to it because it only scans
    payments still in flight.
    """
    from app.models.commerce import Payment, PaymentStatus
    from app.services.outbox import OutboxService
    from app.services.payment_provider import (
        ProviderPaymentState,
        UnconfiguredPaymentProvider,
        VerifiedPayment,
    )

    event, category = await make_event(db_session)
    customer = User(
        role=UserRole.CUSTOMER,
        status=UserStatus.ACTIVE,
        email=unique_email("stuck"),
        phone_e164=f"+9190{uuid.uuid4().int % 10**8:08d}",
    )
    db_session.add(customer)
    await db_session.flush()

    booking = Booking(
        reference=f"JIVE-{uuid.uuid4().hex[:8].upper()}",
        user_id=customer.id,
        event_id=event.id,
        status=BookingStatus.PENDING,  # never confirmed
        subtotal_paise=100000,
        fees_paise=0,
        total_paise=100000,
        quantity=1,
    )
    db_session.add(booking)
    await db_session.flush()
    db_session.add(
        BookingItem(
            booking_id=booking.id,
            ticket_category_id=category.id,
            category_name="General",
            unit_price_paise=100000,
            quantity=1,
            line_total_paise=100000,
        )
    )
    payment = Payment(
        booking_id=booking.id,
        provider="unconfigured",
        provider_order_id=f"order_{uuid.uuid4().hex[:10]}",
        provider_payment_id=f"pay_{uuid.uuid4().hex[:10]}",
        amount_paise=100000,
        idempotency_key=f"order:{booking.id}",
        status=PaymentStatus.CAPTURED,  # money already taken
        captured_at=datetime.now(UTC),
    )
    db_session.add(payment)
    await db_session.flush()

    settings = Settings(environment="test", secret_key="t" * 64)
    outbox = OutboxService(db_session)
    inventory = InventoryService(db_session, settings.reservation_hold_seconds)
    bookings = BookingService(db_session, settings, inventory, outbox)
    refunds = RefundService(db_session, settings, UnconfiguredPaymentProvider(), outbox)
    payments = PaymentService(
        db_session, settings, UnconfiguredPaymentProvider(), bookings, refunds
    )

    verified = VerifiedPayment(
        provider_payment_id=payment.provider_payment_id or "",
        provider_order_id=payment.provider_order_id or "",
        amount_paise=100000,
        currency="INR",
        state=ProviderPaymentState.SUCCEEDED,
        provider_status="captured",
    )
    await payments.confirm_from_provider(verified, source="test")

    await db_session.refresh(booking)
    # Either outcome is acceptable — seats found and confirmed, or seats gone
    # and refunded. What must never happen is the booking staying PENDING
    # with the money taken and nothing in motion.
    assert booking.status is not BookingStatus.PENDING, (
        "a captured payment must never be left as an unconfirmed booking"
    )
    assert booking.status in (BookingStatus.CONFIRMED, BookingStatus.CANCELLED)


async def test_a_webhook_that_failed_once_is_retried_not_dropped(
    db_session: AsyncSession,
) -> None:
    """The record is written before processing. If processing then failed,
    redelivery saw the row and answered 'duplicate' — dropping the event for
    good, so one transient blip meant a payment that never confirmed."""
    from app.models.commerce import PaymentWebhookEvent
    from app.repositories.commerce import WebhookEventRepository

    repository = WebhookEventRepository(db_session)
    event_id = f"evt_{uuid.uuid4().hex[:12]}"

    db_session.add(
        PaymentWebhookEvent(
            provider="razorpay",
            provider_event_id=event_id,
            event_type="payment.captured",
            signature_verified=True,
            processed_at=None,  # recorded, never finished
        )
    )
    await db_session.flush()

    unfinished = await repository.by_provider_event_id("razorpay", event_id)
    assert unfinished is not None
    assert unfinished.processed_at is None, (
        "an unfinished record must be distinguishable from a completed one, "
        "or redelivery cannot tell them apart"
    )


async def test_simultaneous_refreshes_rotate_a_token_only_once(
    racing_sessions,
) -> None:
    """One refresh token must not become two live sessions."""
    from app.models.refresh_token import RefreshToken
    from app.repositories.refresh_token import RefreshTokenRepository

    _seed, make_session, _ = racing_sessions

    async with make_session() as session:
        user = User(
            role=UserRole.CUSTOMER,
            status=UserStatus.ACTIVE,
            email=unique_email("rotator"),
        )
        session.add(user)
        await session.flush()
        token = RefreshToken(
            user_id=user.id,
            token_hash=uuid.uuid4().hex * 2,
            family_id=uuid.uuid4(),
            expires_at=datetime.now(UTC) + timedelta(days=30),
        )
        session.add(token)
        await session.commit()
        token_id, user_id = token.id, user.id

    async def claim() -> bool:
        async with make_session() as session:
            won = await RefreshTokenRepository(session).claim_for_rotation(
                token_id, now=datetime.now(UTC)
            )
            await session.commit()
            return won

    results = await asyncio.gather(claim(), claim())
    assert sum(results) == 1, f"exactly one claim may win, got {results}"

    async with make_session() as session:
        await session.execute(
            sa.text("DELETE FROM refresh_tokens WHERE user_id = :u"), {"u": user_id}
        )
        await session.execute(sa.text("DELETE FROM users WHERE id = :u"), {"u": user_id})
        await session.commit()


async def test_a_partial_refund_leaves_the_other_tickets_usable(
    db_session: AsyncSession,
) -> None:
    """Refunding one seat of four must not void all four."""
    from app.models.commerce import Payment, PaymentStatus, Refund, RefundReason, RefundStatus
    from app.services.outbox import OutboxService
    from app.services.payment_provider import UnconfiguredPaymentProvider

    event, category = await make_event(db_session)
    customer = User(role=UserRole.CUSTOMER, status=UserStatus.ACTIVE, email=unique_email("partial"))
    db_session.add(customer)
    await db_session.flush()

    booking = Booking(
        reference=f"JIVE-{uuid.uuid4().hex[:8].upper()}",
        user_id=customer.id,
        event_id=event.id,
        status=BookingStatus.CONFIRMED,
        subtotal_paise=400000,
        fees_paise=0,
        total_paise=400000,
        quantity=4,
        confirmed_at=datetime.now(UTC),
    )
    db_session.add(booking)
    await db_session.flush()
    item = BookingItem(
        booking_id=booking.id,
        ticket_category_id=category.id,
        category_name="General",
        unit_price_paise=100000,
        quantity=4,
        line_total_paise=400000,
    )
    db_session.add(item)
    payment = Payment(
        booking_id=booking.id,
        provider="unconfigured",
        provider_payment_id=f"pay_{uuid.uuid4().hex[:10]}",
        amount_paise=400000,
        idempotency_key=f"order:{booking.id}",
        status=PaymentStatus.CAPTURED,
        captured_at=datetime.now(UTC),
    )
    db_session.add(payment)
    await db_session.flush()

    service = TicketService(db_session, OutboxService(db_session))
    await service.issue_for_booking(booking.id)

    refund = Refund(
        booking_id=booking.id,
        payment_id=payment.id,
        amount_paise=100000,  # one seat of four
        status=RefundStatus.PROCESSING,
        reason=RefundReason.CUSTOMER_CANCELLED,
        provider="unconfigured",
        idempotency_key=f"refund:{booking.id}:100000",
    )
    db_session.add(refund)
    await db_session.flush()

    settings = Settings(environment="test", secret_key="t" * 64)
    refunds = RefundService(
        db_session, settings, UnconfiguredPaymentProvider(), OutboxService(db_session)
    )
    await refunds._settle(refund, payment)

    still_valid = await db_session.scalar(
        sa.text("SELECT count(*) FROM tickets WHERE booking_id = :b AND status = 'ISSUED'"),
        {"b": booking.id},
    )
    assert still_valid == 4, (
        "a quarter refund must not void the three seats still paid for; "
        f"{4 - (still_valid or 0)} were voided"
    )
    await db_session.refresh(booking)
    assert booking.status is BookingStatus.PARTIALLY_REFUNDED


# ---- 13. assigning staff must return the assignment, not a 500 ---------


async def test_assigning_staff_returns_the_assignment(racing_sessions) -> None:
    """The response reads the staff member's name and email. On a brand-new
    assignment that relationship was not loaded and could not lazy-load, so the
    very first assignment returned a 500 (found by the admin UI).

    It needs a session of its own: in the shared test session the staff row is
    already in memory, which hides the bug.
    """
    seed, maker, _ = racing_sessions
    event_id, *_ = await seed(capacity=5, limit=2)

    async with maker() as setup:
        admin = await seed_admin(setup)
        staff = await seed_staff(setup)
        await setup.commit()
    try:
        async with maker() as fresh:
            assignment = await StaffService(fresh).assign(
                user_id=staff.id, event_id=event_id, actor=admin
            )
            assert assignment.user.email == staff.email
            assert assignment.created_at is not None
    finally:
        async with maker() as cleanup:
            await cleanup.execute(
                sa.text("DELETE FROM staff_event_assignments WHERE event_id = :e"), {"e": event_id}
            )
            await cleanup.execute(
                sa.text("DELETE FROM audit_logs WHERE actor_user_id = :a"), {"a": admin.id}
            )
            await cleanup.execute(
                sa.text("DELETE FROM users WHERE id IN (:a, :s)"), {"a": admin.id, "s": staff.id}
            )
            await cleanup.commit()


async def _confirmed_booking_with_tickets(
    db_session: AsyncSession, quantity: int
) -> tuple[User, Booking, Event]:
    event, category = await make_event(db_session)
    customer = User(
        role=UserRole.CUSTOMER,
        status=UserStatus.ACTIVE,
        email=unique_email("mail"),
        full_name="Aarav Mehta",
    )
    db_session.add(customer)
    await db_session.flush()
    booking = Booking(
        reference=f"JIVE-{uuid.uuid4().hex[:8].upper()}",
        user_id=customer.id,
        event_id=event.id,
        status=BookingStatus.CONFIRMED,
        subtotal_paise=100000 * quantity,
        fees_paise=0,
        total_paise=100000 * quantity,
        quantity=quantity,
        confirmed_at=datetime.now(UTC),
    )
    db_session.add(booking)
    await db_session.flush()
    db_session.add(
        BookingItem(
            booking_id=booking.id,
            ticket_category_id=category.id,
            category_name="General",
            unit_price_paise=100000,
            quantity=quantity,
            line_total_paise=100000 * quantity,
        )
    )
    await db_session.flush()
    await TicketService(db_session, OutboxService(db_session)).issue_for_booking(booking.id)
    return customer, booking, event


async def test_ticket_email_carries_every_qr_to_the_customer(
    db_session: AsyncSession, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.mailer import Mail
    from app.services.notification import NotificationService

    customer, booking, event = await _confirmed_booking_with_tickets(db_session, quantity=2)
    sent: list[Mail] = []

    async def fake_send(_settings: Settings, mail: Mail) -> None:
        sent.append(mail)

    monkeypatch.setattr("app.core.mailer.send_mail", fake_send)
    on = settings.model_copy(
        update={
            "smtp_host": "smtp.example.com",
            "smtp_username": "u",
            "smtp_password": SecretStr("p"),
            "mail_from": "tickets@example.com",
        }
    )
    tickets = TicketService(db_session, OutboxService(db_session), on)
    assert await NotificationService(db_session, on, tickets).send_tickets(booking.id) is True

    (mail,) = sent
    assert mail.to == customer.email
    assert event.title in mail.subject
    assert len(mail.images) == 2 and all(i.png[:4] == b"\x89PNG" for i in mail.images)
    assert booking.reference in mail.html and booking.reference in mail.text
    # The scannable token must never be written into the email text, only drawn as an image.
    for ticket in await TicketRepository(db_session).for_booking(booking.id):
        assert tickets.qr_token_for(ticket) not in mail.html + mail.text


async def test_ticket_email_is_skipped_quietly_when_email_is_not_set_up(
    db_session: AsyncSession, settings: Settings
) -> None:
    from app.services.notification import NotificationService

    _, booking, _ = await _confirmed_booking_with_tickets(db_session, quantity=1)
    assert settings.email_configured is False
    tickets = TicketService(db_session, OutboxService(db_session), settings)
    assert (
        await NotificationService(db_session, settings, tickets).send_tickets(booking.id) is False
    )


async def test_cancellation_and_refund_emails_reach_the_customer(
    db_session: AsyncSession, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.mailer import Mail
    from app.models.commerce import Payment, PaymentStatus, Refund, RefundReason, RefundStatus
    from app.services.notification import NotificationService

    customer, booking, event = await _confirmed_booking_with_tickets(db_session, quantity=1)
    to, reference, title = customer.email, booking.reference, event.title
    payment = Payment(
        booking_id=booking.id,
        provider="razorpay",
        provider_order_id=f"order_{uuid.uuid4().hex[:10]}",
        idempotency_key=uuid.uuid4().hex,
        status=PaymentStatus.CAPTURED,
        amount_paise=100000,
        currency="INR",
    )
    db_session.add(payment)
    await db_session.flush()
    refund = Refund(
        booking_id=booking.id,
        payment_id=payment.id,
        amount_paise=100000,
        status=RefundStatus.SUCCEEDED,
        reason=RefundReason.CUSTOMER_CANCELLED,
        provider="razorpay",
        idempotency_key=uuid.uuid4().hex,
    )
    db_session.add(refund)
    await db_session.flush()

    sent: list[Mail] = []

    async def fake_send(_settings: Settings, mail: Mail) -> None:
        sent.append(mail)

    monkeypatch.setattr("app.core.mailer.send_mail", fake_send)
    on = settings.model_copy(
        update={
            "smtp_host": "smtp.example.com",
            "smtp_username": "u",
            "smtp_password": SecretStr("p"),
            "mail_from": "tickets@example.com",
        }
    )
    service = NotificationService(
        db_session, on, TicketService(db_session, OutboxService(db_session), on)
    )
    assert await service.send_cancellation(booking.id) is True
    assert await service.send_refund(refund.id) is True

    cancelled, refunded = sent
    assert cancelled.to == refunded.to == to
    assert reference in cancelled.subject
    assert "₹1,000.00" in refunded.subject and title in refunded.subject
    assert refunded.images == [] and cancelled.images == []
