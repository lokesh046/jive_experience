"""Ticket, check-in, staff assignment and outbox queries."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any, cast

from sqlalchemy import CursorResult, func, select, update
from sqlalchemy.orm import joinedload

from app.core.pagination import PageParams
from app.models.fulfilment import (
    OutboxMessage,
    OutboxStatus,
    StaffEventAssignment,
    Ticket,
    TicketCheckin,
    TicketStatus,
)
from app.repositories.base import BaseRepository


class TicketRepository(BaseRepository[Ticket]):
    model = Ticket

    async def by_token_hash(self, token_hash: str) -> Ticket | None:
        """Scanner lookup. Indexed by the unique constraint on the hash."""
        return await self.find_one(Ticket.qr_token_hash == token_hash)

    async def for_booking(self, booking_id: uuid.UUID) -> Sequence[Ticket]:
        return await self.list(Ticket.booking_id == booking_id, order_by=[Ticket.serial.asc()])

    async def for_user(
        self, user_id: uuid.UUID, params: PageParams
    ) -> tuple[Sequence[Ticket], int]:
        return await self.paginate(
            params, Ticket.user_id == user_id, order_by=[Ticket.created_at.desc()]
        )

    async def count_for_booking(self, booking_id: uuid.UUID) -> int:
        return await self.count(Ticket.booking_id == booking_id)

    async def check_in(self, ticket_id: uuid.UUID, *, now: datetime) -> bool:
        """Mark a ticket used — atomically, and only once.

        The `status == ISSUED` guard is the entire double-scan defence: two
        simultaneous scans of the same QR both run this UPDATE, PostgreSQL
        serialises them, and exactly one sees a row affected.
        """
        statement = (
            update(Ticket)
            .where(Ticket.id == ticket_id, Ticket.status == TicketStatus.ISSUED)
            .values(status=TicketStatus.CHECKED_IN, checked_in_at=now)
        )
        result = cast("CursorResult[Any]", await self.session.execute(statement))
        return (result.rowcount or 0) == 1

    async def invalidate_for_booking(
        self, booking_id: uuid.UUID, *, status: TicketStatus, now: datetime
    ) -> int:
        """Void a booking's unused tickets after a cancellation or refund.

        Checked-in tickets are left alone: the person already attended, and
        rewriting that would corrupt the attendance record.
        """
        statement = (
            update(Ticket)
            .where(
                Ticket.booking_id == booking_id,
                Ticket.status == TicketStatus.ISSUED,
            )
            .values(status=status, invalidated_at=now)
        )
        result = cast("CursorResult[Any]", await self.session.execute(statement))
        return result.rowcount or 0

    async def attendance(self, event_id: uuid.UUID) -> dict[str, int]:
        """Issued vs checked-in counts for the event dashboard."""
        statement = (
            select(Ticket.status, func.count())
            .where(Ticket.event_id == event_id)
            .group_by(Ticket.status)
        )
        rows = (await self.session.execute(statement)).all()
        counts = {str(row[0]): int(row[1]) for row in rows}
        counts["TOTAL"] = sum(counts.values())
        return counts


class TicketCheckinRepository(BaseRepository[TicketCheckin]):
    model = TicketCheckin

    async def recent_for_event(
        self, event_id: uuid.UUID, params: PageParams
    ) -> tuple[Sequence[TicketCheckin], int]:
        return await self.paginate(
            params,
            TicketCheckin.event_id == event_id,
            order_by=[TicketCheckin.scanned_at.desc()],
        )


class StaffAssignmentRepository(BaseRepository[StaffEventAssignment]):
    model = StaffEventAssignment

    async def is_assigned(self, user_id: uuid.UUID, event_id: uuid.UUID) -> bool:
        """Role is not enough — a staff member must be on this event."""
        return await self.exists(
            StaffEventAssignment.user_id == user_id,
            StaffEventAssignment.event_id == event_id,
            StaffEventAssignment.revoked_at.is_(None),
        )

    async def for_user(self, user_id: uuid.UUID) -> Sequence[StaffEventAssignment]:
        return await self.list(
            StaffEventAssignment.user_id == user_id,
            StaffEventAssignment.revoked_at.is_(None),
            order_by=[StaffEventAssignment.created_at.desc()],
        )

    async def for_event(self, event_id: uuid.UUID) -> Sequence[StaffEventAssignment]:
        statement = (
            select(StaffEventAssignment)
            .where(
                StaffEventAssignment.event_id == event_id,
                StaffEventAssignment.revoked_at.is_(None),
            )
            .options(joinedload(StaffEventAssignment.user))
        )
        return (await self.session.execute(statement)).scalars().all()

    async def existing(
        self, user_id: uuid.UUID, event_id: uuid.UUID
    ) -> StaffEventAssignment | None:
        return await self.find_one(
            StaffEventAssignment.user_id == user_id,
            StaffEventAssignment.event_id == event_id,
        )


class OutboxRepository(BaseRepository[OutboxMessage]):
    model = OutboxMessage

    async def claim(
        self, *, worker_id: str, now: datetime, limit: int = 20
    ) -> Sequence[OutboxMessage]:
        """Take a batch of due work.

        `FOR UPDATE SKIP LOCKED` is what lets several worker processes share
        one queue: each claims rows the others are not holding, with no
        coordination and no double processing.
        """
        subquery = (
            select(OutboxMessage.id)
            .where(
                OutboxMessage.status.in_((OutboxStatus.PENDING, OutboxStatus.PROCESSING)),
                OutboxMessage.available_at <= now,
                OutboxMessage.attempts < OutboxMessage.max_attempts,
            )
            .order_by(OutboxMessage.available_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
            .scalar_subquery()
        )
        statement = (
            update(OutboxMessage)
            .where(OutboxMessage.id.in_(subquery))
            .values(
                status=OutboxStatus.PROCESSING,
                locked_at=now,
                locked_by=worker_id,
                attempts=OutboxMessage.attempts + 1,
            )
            .returning(OutboxMessage)
        )
        return (await self.session.execute(statement)).scalars().all()

    async def mark_done(self, message_id: uuid.UUID, *, now: datetime) -> None:
        await self.session.execute(
            update(OutboxMessage)
            .where(OutboxMessage.id == message_id)
            .values(
                status=OutboxStatus.DONE,
                completed_at=now,
                locked_at=None,
                locked_by=None,
                last_error=None,
            )
        )

    async def mark_retry(self, message_id: uuid.UUID, *, retry_at: datetime, error: str) -> None:
        """Hand the message back for a later attempt, or give up.

        A message that has used its attempts becomes FAILED rather than
        looping forever; it stays in the table for an operator to inspect.
        """
        await self.session.execute(
            update(OutboxMessage)
            .where(OutboxMessage.id == message_id)
            .values(
                status=OutboxStatus.PENDING,
                available_at=retry_at,
                locked_at=None,
                locked_by=None,
                last_error=error[:2000],
            )
        )

    async def mark_failed(self, message_id: uuid.UUID, *, error: str) -> None:
        await self.session.execute(
            update(OutboxMessage)
            .where(OutboxMessage.id == message_id)
            .values(
                status=OutboxStatus.FAILED,
                locked_at=None,
                locked_by=None,
                last_error=error[:2000],
            )
        )

    async def release_stale_locks(self, *, older_than: datetime) -> int:
        """Recover work abandoned by a worker that died mid-message."""
        statement = (
            update(OutboxMessage)
            .where(
                OutboxMessage.status == OutboxStatus.PROCESSING,
                OutboxMessage.locked_at.is_not(None),
                OutboxMessage.locked_at <= older_than,
            )
            .values(status=OutboxStatus.PENDING, locked_at=None, locked_by=None)
        )
        result = cast("CursorResult[Any]", await self.session.execute(statement))
        return result.rowcount or 0

    async def pending_count(self) -> int:
        return await self.count(OutboxMessage.status == OutboxStatus.PENDING)
