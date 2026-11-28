"""Cancelling a confirmed booking puts its seats back on sale, once."""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models.commerce import Booking
from app.models.event import Event
from app.models.user import User
from app.services.outbox import OutboxService
from app.services.payment_provider import UnconfiguredPaymentProvider
from app.services.refund import RefundService
from tests.integration.conftest import seed_admin
from tests.integration.test_review_fixes import _confirmed_booking_with_tickets

pytestmark = pytest.mark.integration


async def _sold(session: AsyncSession, event_id: object) -> int:
    session.expire_all()
    return int(
        (
            await session.execute(
                sa.text("SELECT sold_count FROM ticket_categories WHERE event_id = :e"),
                {"e": event_id},
            )
        ).scalar_one()
    )


async def _cancel(
    session: AsyncSession, settings: Settings, booking: Booking, event: Event, admin: User
) -> None:
    service = RefundService(
        session, settings, UnconfiguredPaymentProvider(), OutboxService(session)
    )
    await service.cancel_booking(
        booking=booking, event=event, actor=admin, customer_initiated=False
    )


async def test_cancelling_a_confirmed_booking_returns_its_seats_to_sale(
    db_session: AsyncSession, settings: Settings
) -> None:
    _customer, booking, event = await _confirmed_booking_with_tickets(db_session, 3)
    admin = await seed_admin(db_session)
    event_id, booking_id = event.id, booking.id
    await db_session.execute(
        sa.text("UPDATE ticket_categories SET sold_count = 5 WHERE event_id = :e"), {"e": event_id}
    )
    await db_session.commit()

    await _cancel(db_session, settings, booking, event, admin)
    assert await _sold(db_session, event_id) == 2  # 5 sold, minus the 3 that were cancelled

    # A second cancel is refused, and takes nothing more back.
    again = await db_session.get(Booking, booking_id)
    assert again is not None
    with pytest.raises(Exception, match="already cancelled"):
        await _cancel(db_session, settings, again, event, admin)
    assert await _sold(db_session, event_id) == 2


async def test_a_booking_with_a_scanned_ticket_cannot_be_cancelled_by_the_customer(
    db_session: AsyncSession, settings: Settings
) -> None:
    _customer, booking, event = await _confirmed_booking_with_tickets(db_session, 2)
    booking_id, event_id = booking.id, event.id
    await db_session.execute(
        sa.text(
            "UPDATE tickets SET status = 'CHECKED_IN', checked_in_at = now() "
            "WHERE id = (SELECT id FROM tickets WHERE booking_id = :b LIMIT 1)"
        ),
        {"b": booking_id},
    )
    await db_session.commit()
    db_session.expire_all()
    booking = await db_session.get(Booking, booking_id)
    event = await db_session.get(Event, event_id)
    assert booking is not None and event is not None

    service = RefundService(
        session=db_session,
        settings=settings,
        provider=UnconfiguredPaymentProvider(),
        outbox=OutboxService(db_session),
    )
    quote = await service.quote(booking=booking, event=event)

    assert not quote.eligible
    assert "already been used" in quote.reason
