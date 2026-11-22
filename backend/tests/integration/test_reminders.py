"""Reminder emails: who is due, that each booking is queued once, and what is sent."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.mailer import Mail
from app.models.commerce import Booking, BookingStatus
from app.models.event import Event
from app.services.notification import NotificationService
from app.services.outbox import OutboxService
from app.services.ticket import TicketService
from tests.integration.test_review_fixes import _confirmed_booking_with_tickets

pytestmark = pytest.mark.integration


def _on(settings: Settings) -> Settings:
    return settings.model_copy(
        update={
            "smtp_host": "smtp.example.com",
            "smtp_username": "u",
            "smtp_password": SecretStr("p"),
            "mail_from": "tickets@example.com",
        }
    )


async def _set_times(
    session: AsyncSession,
    booking: Booking,
    event: Event,
    *,
    starts_in: timedelta,
    booked_ago: timedelta,
) -> None:
    now = datetime.now(UTC)
    await session.execute(
        sa.text("UPDATE events SET starts_at = :s WHERE id = :i"),
        {"s": now + starts_in, "i": event.id},
    )
    await session.execute(
        sa.text("UPDATE bookings SET confirmed_at = :c WHERE id = :i"),
        {"c": now - booked_ago, "i": booking.id},
    )
    await session.commit()


def _service(session: AsyncSession, settings: Settings) -> NotificationService:
    on = _on(settings)
    return NotificationService(session, on, TicketService(session, OutboxService(session), on))


async def test_only_bookings_inside_the_window_are_due_and_each_is_queued_once(
    db_session: AsyncSession, settings: Settings
) -> None:
    _, soon, soon_event = await _confirmed_booking_with_tickets(db_session, quantity=1)
    _, far, far_event = await _confirmed_booking_with_tickets(db_session, quantity=1)
    _, last_minute, lm_event = await _confirmed_booking_with_tickets(db_session, quantity=1)
    _, cancelled, c_event = await _confirmed_booking_with_tickets(db_session, quantity=1)
    ids = {b.id: b.reference for b in (soon, far, last_minute, cancelled)}

    await _set_times(
        db_session, soon, soon_event, starts_in=timedelta(hours=20), booked_ago=timedelta(days=3)
    )
    await _set_times(
        db_session, far, far_event, starts_in=timedelta(hours=40), booked_ago=timedelta(days=3)
    )
    # Bought 2 hours ago for a show starting in 20 hours: it does not need a "tomorrow" email.
    await _set_times(
        db_session,
        last_minute,
        lm_event,
        starts_in=timedelta(hours=20),
        booked_ago=timedelta(hours=2),
    )
    await _set_times(
        db_session, cancelled, c_event, starts_in=timedelta(hours=20), booked_ago=timedelta(days=3)
    )
    await db_session.execute(
        sa.text("UPDATE bookings SET status = :s WHERE id = :i"),
        {"s": BookingStatus.CANCELLED.value, "i": cancelled.id},
    )
    await db_session.commit()

    service = _service(db_session, settings)
    assert await service.enqueue_due_reminders(datetime.now(UTC)) >= 1
    queued = (
        (
            await db_session.execute(
                sa.text("SELECT dedup_key FROM outbox_messages WHERE topic = 'booking.reminder'")
            )
        )
        .scalars()
        .all()
    )
    wanted = {f"booking.reminder:{soon.id}"}
    assert wanted <= set(queued)
    for other in (far, last_minute, cancelled):
        assert f"booking.reminder:{other.id}" not in queued, ids[other.id]

    # A second sweep finds nothing new: the first one already queued it.
    assert await service.enqueue_due_reminders(datetime.now(UTC)) == 0


async def test_reminder_email_has_the_tickets_and_skips_a_cancelled_booking(
    db_session: AsyncSession, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    customer, booking, event = await _confirmed_booking_with_tickets(db_session, quantity=2)
    to, reference, title, booking_id = customer.email, booking.reference, event.title, booking.id
    sent: list[Mail] = []

    async def fake_send(_settings: Settings, mail: Mail) -> None:
        sent.append(mail)

    monkeypatch.setattr("app.core.mailer.send_mail", fake_send)
    service = _service(db_session, settings)

    assert await service.send_reminder(booking_id) is True
    (mail,) = sent
    assert mail.to == to and mail.subject.startswith("Reminder:") and title in mail.subject
    assert len(mail.images) == 2 and reference in mail.html

    await db_session.execute(
        sa.text("UPDATE bookings SET status = 'CANCELLED' WHERE id = :i"), {"i": booking_id}
    )
    await db_session.commit()
    db_session.expire_all()  # the raw UPDATE bypassed the ORM's copy of the booking
    assert await service.send_reminder(booking_id) is False
    assert len(sent) == 1
