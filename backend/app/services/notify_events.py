"""What each thing that happens means to whom: the words, the link, how loud.

Kept apart from the producers so the wording lives in one place, and a producer only says
"this happened". Every method is safe to run twice: the dedup keys make a repeat a no-op.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.money import format_inr
from app.models.commerce import Booking, Refund
from app.models.event import Event, EventStatus, TicketCategory
from app.models.lead import Enquiry
from app.models.waitlist import WaitlistEntry
from app.repositories.user import UserRepository
from app.services.notification_center import NotificationCenter

logger = structlog.get_logger(__name__)

# How full a night must be before the team hears about it.
FILLING_AT = (80, 95)
DOORS_BEFORE = timedelta(minutes=60)


def _when(event: Event) -> str:
    zone = ZoneInfo(event.timezone or "Asia/Kolkata")
    return event.starts_at.astimezone(zone).strftime("%a %d %b, %I:%M %p").replace(" 0", " ")


class Notifier:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.center = NotificationCenter(session)

    async def _booking(self, booking_id: uuid.UUID) -> tuple[Booking, Event] | None:
        booking = await self.session.get(Booking, booking_id)
        if booking is None:
            return None
        event = await self.session.get(Event, booking.event_id)
        return (booking, event) if event is not None else None

    # ------------------------------------------------------------ customers ---

    async def tickets_ready(self, booking_id: uuid.UUID) -> None:
        found = await self._booking(booking_id)
        if found is None:
            return
        booking, event = found
        await self.center.notify(
            [booking.user_id],
            kind="booking.tickets_ready",
            category="bookings",
            title=f"Your tickets for {event.title} are ready",
            body=f"{_when(event)}. Show the QR code at the gate.",
            link=f"/tickets/{booking.reference}",
            dedup_key=f"tickets_ready:{booking.id}",
        )

    async def booking_cancelled(self, booking_id: uuid.UUID) -> None:
        found = await self._booking(booking_id)
        if found is None:
            return
        booking, event = found
        by_us = event.status is EventStatus.CANCELLED
        await self.center.notify(
            [booking.user_id],
            kind="booking.cancelled",
            category="bookings",
            severity="warn" if by_us else "info",
            title=(
                f"{event.title} has been cancelled"
                if by_us
                else f"Booking {booking.reference} cancelled"
            ),
            body="Your tickets no longer work."
            + (" A refund is on its way." if booking.total_paise else ""),
            link=f"/tickets/{booking.reference}",
            dedup_key=f"booking_cancelled:{booking.id}",
        )

    async def refund_completed(self, refund_id: uuid.UUID) -> None:
        refund = await self.session.get(Refund, refund_id)
        if refund is None:
            return
        found = await self._booking(refund.booking_id)
        if found is None:
            return
        booking, event = found
        await self.center.notify(
            [booking.user_id],
            kind="refund.completed",
            category="bookings",
            title=f"Refund of {format_inr(refund.amount_paise)} sent",
            body=f"For {event.title}. It can take a few days to show on your statement.",
            link=f"/tickets/{booking.reference}",
            dedup_key=f"refund_completed:{refund.id}",
        )

    async def event_reminder(self, booking_id: uuid.UUID) -> None:
        found = await self._booking(booking_id)
        if found is None:
            return
        booking, event = found
        await self.center.notify(
            [booking.user_id],
            kind="booking.reminder",
            category="reminders",
            title=f"{event.title} is coming up",
            body=f"{_when(event)}. Your tickets are in My tickets.",
            link=f"/tickets/{booking.reference}",
            dedup_key=f"reminder:{booking.id}",
        )

    async def waitlist_available(self, entry_id: uuid.UUID) -> None:
        entry = await self.session.get(WaitlistEntry, entry_id)
        if entry is None:
            return
        stamp = entry.notified_at.isoformat() if entry.notified_at else ""
        user = await UserRepository(self.session).by_email(entry.email)
        event = await self.session.get(Event, entry.event_id)
        if user is None or event is None:
            return  # they joined without an account: only the email reaches them
        await self.center.notify(
            [user.id],
            kind="waitlist.available",
            category="waitlist",
            title=f"Tickets are back for {event.title}",
            body="First come, first served. We cannot hold them.",
            link=f"/events/{event.slug}#tickets",
            dedup_key=f"waitlist:{entry.id}:{stamp}",
        )

    # --------------------------------------------------------------- admins ---

    async def enquiry_received(self, enquiry_id: uuid.UUID) -> None:
        enquiry = await self.session.get(Enquiry, enquiry_id)
        if enquiry is None:
            return
        await self.center.notify_admins(
            kind="enquiry.received",
            category="enquiries",
            title=f"New enquiry from {enquiry.name}",
            body=(enquiry.message or "")[:140],
            link="/admin/inbox",
            dedup_key=f"enquiry:{enquiry.id}",
        )

    async def sales_progress(self, event_id: uuid.UUID) -> None:
        """Tell the team when a night is filling, and once when it is full."""
        event = await self.session.get(Event, event_id)
        if event is None:
            return
        row = (
            await self.session.execute(
                select(
                    func.coalesce(func.sum(TicketCategory.capacity), 0),
                    func.coalesce(func.sum(TicketCategory.sold_count), 0),
                ).where(TicketCategory.event_id == event_id, TicketCategory.is_active.is_(True))
            )
        ).one()
        capacity, sold = int(row[0]), int(row[1])
        if capacity <= 0:
            return
        percent = sold * 100 // capacity
        if sold >= capacity:
            await self.center.notify_admins(
                kind="sales.sold_out",
                category="sales",
                title=f"{event.title} is sold out",
                body=f"All {capacity} tickets are sold.",
                link=f"/admin/events/{event.id}",
                dedup_key=f"sold_out:{event.id}",
            )
            return
        for mark in reversed(FILLING_AT):
            if percent >= mark:
                await self.center.notify_admins(
                    kind="sales.filling",
                    category="sales",
                    severity="warn",
                    title=f"{event.title} is {mark}% sold",
                    body=f"{sold} of {capacity} tickets sold.",
                    link=f"/admin/events/{event.id}",
                    dedup_key=f"filling:{event.id}:{mark}",
                )
                break

    async def payment_without_seats(self, booking_id: uuid.UUID) -> None:
        found = await self._booking(booking_id)
        if found is None:
            return
        booking, event = found
        await self.center.notify_admins(
            kind="payment.refunded_no_seats",
            category="payments",
            severity="critical",
            title=f"Paid, but the seats were gone: {booking.reference}",
            body=f"{event.title}. The customer was charged, so a full refund was started.",
            link="/admin/bookings",
            dedup_key=f"no_seats:{booking.id}",
        )

    async def payment_recovered(self, booking_id: uuid.UUID) -> None:
        found = await self._booking(booking_id)
        if found is None:
            return
        booking, event = found
        await self.center.notify_admins(
            kind="payment.recovered",
            category="payments",
            severity="warn",
            title=f"A payment was found by the safety check: {booking.reference}",
            body=(
                f"{event.title}. The payment confirmation never reached us, so the booking was "
                "confirmed later. If this happens often, check the payment webhook."
            ),
            link="/admin/bookings",
            dedup_key=f"recovered:{booking.id}",
        )

    async def refund_failed(self, refund_id: uuid.UUID) -> None:
        refund = await self.session.get(Refund, refund_id)
        if refund is None:
            return
        found = await self._booking(refund.booking_id)
        reference = found[0].reference if found else "a booking"
        await self.center.notify_admins(
            kind="refund.failed",
            category="payments",
            severity="critical",
            title=f"A refund of {format_inr(refund.amount_paise)} failed ({reference})",
            body=(refund.failure_reason or "The payment provider refused it.")[:200],
            link="/admin/bookings",
            dedup_key=f"refund_failed:{refund.id}",
        )

    async def gave_up(self, topic: str, error: str, message_id: uuid.UUID) -> None:
        await self.center.notify_admins(
            kind="system.gave_up",
            category="system",
            severity="critical",
            title=f"A background job failed for good: {topic}",
            body=error[:300],
            dedup_key=f"gave_up:{message_id}",
        )

    # ----------------------------------------------------------------- gate ---

    async def doors_open_soon(self, now: datetime) -> int:
        """Once per person per night, an hour before the doors, to whoever is working it."""
        rows = (
            await self.session.execute(
                select(Event).where(
                    Event.status == EventStatus.PUBLISHED,
                    Event.starts_at > now,
                    Event.starts_at <= now + DOORS_BEFORE,
                )
            )
        ).scalars()
        told = 0
        for event in rows:
            told += await self.center.notify_event_staff(
                event.id,
                kind="gate.doors_soon",
                category="gate",
                title=f"Doors open soon: {event.title}",
                body=f"Starts {_when(event)}. Open the scanner when you are at the gate.",
                link="/scan",
                dedup_key=f"doors:{event.id}",
            )
        return told

    async def suspicious_scan(self, event_id: uuid.UUID, serial: str, result: str) -> None:
        event = await self.session.get(Event, event_id)
        if event is None:
            return
        reasons = {
            "ALREADY_USED": "was already used",
            "CANCELLED": "was cancelled",
            "REFUNDED": "was refunded",
        }
        await self.center.notify_event_staff(
            event_id,
            include_admins=True,
            kind="gate.refused_ticket",
            category="gate",
            severity="warn",
            title=f"A ticket was turned away at {event.title}",
            body=f"{serial} {reasons.get(result, 'was refused')}.",
            link=f"/admin/events/{event.id}",
            dedup_key=f"scan:{serial}:{result}:{datetime.now(UTC):%Y%m%d%H}",
        )
