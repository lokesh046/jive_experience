"""Ticket issuance and QR scanning.

One QR per purchased unit — four tickets means four distinct codes, because
four different people walk through the gate.

Security of the QR itself:

* the token is 32 cryptographically random bytes, so it cannot be guessed;
* only a SHA-256 digest is stored, so a database disclosure yields no working
  tickets;
* the QR carries the token and nothing else — no name, no phone, no booking
  reference — so a photographed ticket leaks no personal data.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, PermissionDeniedError
from app.core.pagination import PageParams
from app.core.security import generate_opaque_token, hash_refresh_token
from app.models.commerce import Booking, BookingStatus
from app.models.event import Event
from app.models.fulfilment import CheckinResult, Ticket, TicketCheckin, TicketStatus
from app.models.user import User, UserRole
from app.repositories.catalogue import EventRepository
from app.repositories.commerce import BookingRepository
from app.repositories.fulfilment import (
    StaffAssignmentRepository,
    TicketCheckinRepository,
    TicketRepository,
)
from app.services.audit import AuditService
from app.services.outbox import TOPIC_TICKETS_ISSUED, OutboxService

logger = structlog.get_logger(__name__)

QR_TOKEN_BYTES = 32


def hash_qr_token(token: str) -> str:
    """SHA-256 of the QR token.

    A plain digest, not a password hash: the token already carries 256 bits of
    entropy, so it is not brute-forceable, and a slow KDF would add latency to
    every gate scan.
    """
    return hash_refresh_token(token)


@dataclass(frozen=True, slots=True)
class IssuedTicket:
    ticket: Ticket
    qr_token: str
    """Returned once, at issue time. Never recoverable afterwards."""


@dataclass(frozen=True, slots=True)
class ScanOutcome:
    result: CheckinResult
    ticket: Ticket | None
    message: str

    @property
    def ok(self) -> bool:
        return self.result is CheckinResult.SUCCESS


class TicketService:
    def __init__(self, session: AsyncSession, outbox: OutboxService) -> None:
        self.session = session
        self.outbox = outbox
        self.tickets = TicketRepository(session)
        self.checkins = TicketCheckinRepository(session)
        self.assignments = StaffAssignmentRepository(session)
        self.bookings = BookingRepository(session)
        self.events = EventRepository(session)
        self.audit = AuditService(session)

    # -------------------------------------------------------- issuance ---

    async def issue_for_booking(self, booking_id: uuid.UUID) -> list[IssuedTicket]:
        """Create one ticket per purchased unit. Idempotent.

        Called by the worker from the `booking.confirmed` outbox message, so
        it must tolerate running twice: if tickets already exist it returns
        without creating more.
        """
        booking = await self.bookings.get(booking_id)
        if booking is None:
            raise NotFoundError("Booking not found.", code="BOOKING_NOT_FOUND")
        if booking.status is not BookingStatus.CONFIRMED:
            logger.info(
                "ticket_issue_skipped_unconfirmed",
                booking_id=str(booking_id),
                status=booking.status.value,
            )
            return []

        if await self.tickets.count_for_booking(booking.id):
            logger.info("tickets_already_issued", booking_id=str(booking_id))
            return []

        items = await self.bookings.items(booking.id)
        now = datetime.now(UTC)
        issued: list[IssuedTicket] = []
        serial_index = 0

        for item in items:
            for _ in range(item.quantity):
                serial_index += 1
                token = generate_opaque_token(QR_TOKEN_BYTES)
                ticket = Ticket(
                    booking_id=booking.id,
                    booking_item_id=item.id,
                    event_id=booking.event_id,
                    ticket_category_id=item.ticket_category_id,
                    user_id=booking.user_id,
                    serial=f"{booking.reference}-{serial_index:02d}",
                    qr_token_hash=hash_qr_token(token),
                    status=TicketStatus.ISSUED,
                    issued_at=now,
                )
                self.tickets.add(ticket)
                issued.append(IssuedTicket(ticket=ticket, qr_token=token))

        try:
            await self.session.flush()
        except IntegrityError:
            # Another worker issued them between the count and the insert.
            await self.session.rollback()
            logger.info("tickets_issued_concurrently", booking_id=str(booking_id))
            return []

        await self.outbox.enqueue(
            topic=TOPIC_TICKETS_ISSUED,
            payload={
                "booking_id": str(booking.id),
                "ticket_count": len(issued),
            },
            dedup_key=f"tickets.issued:{booking.id}",
        )
        await self.session.commit()

        logger.info("tickets_issued", booking_id=str(booking.id), ticket_count=len(issued))
        return issued

    # ----------------------------------------------------- customer reads ---

    async def for_booking(self, booking: Booking, *, customer: User) -> Sequence[Ticket]:
        if booking.user_id != customer.id:
            raise NotFoundError("Booking not found.", code="BOOKING_NOT_FOUND")
        return await self.tickets.for_booking(booking.id)

    async def for_customer(
        self, customer: User, params: PageParams
    ) -> tuple[Sequence[Ticket], int]:
        return await self.tickets.for_user(customer.id, params)

    # ------------------------------------------------------------ scanning ---

    async def scan(
        self,
        *,
        qr_token: str,
        event_id: uuid.UUID,
        staff: User,
        device_label: str | None = None,
    ) -> ScanOutcome:
        """Validate a QR code and check the holder in, atomically.

        The whole gate flow in one place. Three things are checked before
        anything is written — that this staff member works this event, that
        the ticket belongs to this event, and that it is still valid — and the
        check-in itself is a conditional UPDATE, so two simultaneous scans of
        the same code produce exactly one success.

        Every outcome is recorded, failures included: a run of WRONG_EVENT
        scans is how you find out staff are on the wrong gate.
        """
        now = datetime.now(UTC)

        if staff.role is UserRole.EVENT_STAFF and not await self.assignments.is_assigned(
            staff.id, event_id
        ):
            # Role alone is never enough.
            return await self._record(
                result=CheckinResult.NOT_ASSIGNED,
                ticket=None,
                event_id=event_id,
                staff=staff,
                now=now,
                device_label=device_label,
                message="You are not assigned to this event.",
            )

        ticket = await self.tickets.by_token_hash(hash_qr_token(qr_token))

        if ticket is None:
            return await self._record(
                result=CheckinResult.INVALID,
                ticket=None,
                event_id=event_id,
                staff=staff,
                now=now,
                device_label=device_label,
                message="This QR code is not a valid ticket.",
            )

        if ticket.event_id != event_id:
            return await self._record(
                result=CheckinResult.WRONG_EVENT,
                ticket=ticket,
                event_id=event_id,
                staff=staff,
                now=now,
                device_label=device_label,
                message="This ticket is for a different event.",
            )

        if ticket.status is TicketStatus.CHECKED_IN:
            checked_at = ticket.checked_in_at.isoformat() if ticket.checked_in_at else ""
            return await self._record(
                result=CheckinResult.ALREADY_USED,
                ticket=ticket,
                event_id=event_id,
                staff=staff,
                now=now,
                device_label=device_label,
                message=f"This ticket was already used at {checked_at}.",
            )

        if ticket.status is TicketStatus.CANCELLED:
            return await self._record(
                result=CheckinResult.CANCELLED,
                ticket=ticket,
                event_id=event_id,
                staff=staff,
                now=now,
                device_label=device_label,
                message="This ticket was cancelled.",
            )

        if ticket.status is TicketStatus.REFUNDED:
            return await self._record(
                result=CheckinResult.REFUNDED,
                ticket=ticket,
                event_id=event_id,
                staff=staff,
                now=now,
                device_label=device_label,
                message="This ticket was refunded.",
            )

        # The atomic step. If this affects no rows another scanner won the
        # race in the microseconds since the status check above.
        if not await self.tickets.check_in(ticket.id, now=now):
            await self.session.refresh(ticket)
            return await self._record(
                result=CheckinResult.ALREADY_USED,
                ticket=ticket,
                event_id=event_id,
                staff=staff,
                now=now,
                device_label=device_label,
                message="This ticket was already used.",
            )

        outcome = await self._record(
            result=CheckinResult.SUCCESS,
            ticket=ticket,
            event_id=event_id,
            staff=staff,
            now=now,
            device_label=device_label,
            message="Checked in.",
        )
        logger.info(
            "ticket_checked_in",
            ticket_id=str(ticket.id),
            event_id=str(event_id),
            staff_id=str(staff.id),
        )
        return outcome

    async def _record(
        self,
        *,
        result: CheckinResult,
        ticket: Ticket | None,
        event_id: uuid.UUID,
        staff: User,
        now: datetime,
        device_label: str | None,
        message: str,
    ) -> ScanOutcome:
        self.session.add(
            TicketCheckin(
                ticket_id=ticket.id if ticket else None,
                event_id=event_id,
                staff_user_id=staff.id,
                result=result,
                scanned_at=now,
                device_label=device_label,
            )
        )
        await self.session.commit()
        if ticket is not None:
            await self.session.refresh(ticket)
        return ScanOutcome(result=result, ticket=ticket, message=message)

    # --------------------------------------------------------- reporting ---

    async def attendance(self, event_id: uuid.UUID) -> dict[str, int]:
        return await self.tickets.attendance(event_id)

    async def assert_staff_may_view(self, staff: User, event_id: uuid.UUID) -> Event:
        """Staff may only see events they are assigned to; admins see all."""
        event = await self.events.get(event_id)
        if event is None:
            raise NotFoundError("Event not found.", code="EVENT_NOT_FOUND")
        if staff.role is UserRole.ADMIN:
            return event
        if not await self.assignments.is_assigned(staff.id, event_id):
            raise PermissionDeniedError(
                "You are not assigned to this event.", code="NOT_ASSIGNED_TO_EVENT"
            )
        return event
