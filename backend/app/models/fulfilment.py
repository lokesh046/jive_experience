"""Fulfilment: tickets, check-ins, staff assignments and the outbox.

One QR ticket is issued per purchased unit — four tickets means four distinct
QR codes, because four different people walk through the gate.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:  # pragma: no cover
    from app.models.event import Event
    from app.models.user import User


class TicketStatus(StrEnum):
    ISSUED = "ISSUED"
    CHECKED_IN = "CHECKED_IN"
    CANCELLED = "CANCELLED"
    REFUNDED = "REFUNDED"


class CheckinResult(StrEnum):
    """Every outcome the scanner can show, including the failures.

    Failures are recorded too: a run of WRONG_EVENT scans is how you discover
    that staff are working the wrong gate.
    """

    SUCCESS = "SUCCESS"
    ALREADY_USED = "ALREADY_USED"
    WRONG_EVENT = "WRONG_EVENT"
    CANCELLED = "CANCELLED"
    REFUNDED = "REFUNDED"
    INVALID = "INVALID"
    NOT_ASSIGNED = "NOT_ASSIGNED"
    EXPIRED = "EXPIRED"


class OutboxStatus(StrEnum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    DONE = "DONE"
    FAILED = "FAILED"


def _pg_enum(enum_cls: type[StrEnum], name: str) -> Enum:
    return Enum(enum_cls, name=name, values_callable=lambda e: [member.value for member in e])


ticket_status_enum = _pg_enum(TicketStatus, "ticket_status")
checkin_result_enum = _pg_enum(CheckinResult, "checkin_result")
outbox_status_enum = _pg_enum(OutboxStatus, "outbox_status")


class Ticket(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One admission, with its own QR token.

    Only a SHA-256 digest of the token is stored. A database disclosure
    therefore does not yield usable tickets, and the QR itself carries no
    personal data — just the opaque token.
    """

    __tablename__ = "tickets"

    booking_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bookings.id", ondelete="CASCADE"), nullable=False
    )
    booking_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("booking_items.id", ondelete="CASCADE"), nullable=False
    )
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("events.id", ondelete="RESTRICT"), nullable=False
    )
    ticket_category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ticket_categories.id", ondelete="RESTRICT"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )

    # Human-readable, e.g. "JIVE-7F3K2A-03".
    serial: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    # SHA-256 hex of the opaque QR token. The token is shown once, never stored.
    qr_token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)

    status: Mapped[TicketStatus] = mapped_column(
        ticket_status_enum, nullable=False, default=TicketStatus.ISSUED
    )

    attendee_name: Mapped[str | None] = mapped_column(String(120))
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    checked_in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "(status <> 'CHECKED_IN') OR (checked_in_at IS NOT NULL)",
            name="checked_in_has_timestamp",
        ),
        Index("ix_tickets_booking_id", "booking_id"),
        Index("ix_tickets_user_id", "user_id"),
        # The scanner's lookup, and the attendance report.
        Index("ix_tickets_event_id_status", "event_id", "status"),
    )


class TicketCheckin(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An audit row for every scan — successful or not."""

    __tablename__ = "ticket_checkins"

    ticket_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tickets.id", ondelete="SET NULL")
    )
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("events.id", ondelete="CASCADE"), nullable=False
    )
    staff_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    result: Mapped[CheckinResult] = mapped_column(checkin_result_enum, nullable=False)
    scanned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    device_label: Mapped[str | None] = mapped_column(String(120))

    __table_args__ = (
        Index("ix_ticket_checkins_event_id_scanned_at", "event_id", "scanned_at"),
        Index("ix_ticket_checkins_ticket_id", "ticket_id"),
        Index("ix_ticket_checkins_staff_user_id", "staff_user_id"),
    )


class StaffEventAssignment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Which events a staff member may scan.

    Role alone is never enough: EVENT_STAFF plus an assignment row is what
    authorises a scan, so a staff member cannot work an event they were not
    put on.
    """

    __tablename__ = "staff_event_assignments"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("events.id", ondelete="CASCADE"), nullable=False
    )
    assigned_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # The assignment list always shows who the staff member is.
    user: Mapped[User] = relationship(foreign_keys=[user_id], lazy="joined")
    event: Mapped[Event] = relationship(lazy="joined")

    __table_args__ = (
        UniqueConstraint("user_id", "event_id", name="uq_staff_event_assignments_user_id_event_id"),
        Index("ix_staff_event_assignments_event_id", "event_id"),
    )


class OutboxMessage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Durable work queued inside a business transaction.

    An email sent with `asyncio.create_task` after a commit is lost when the
    process restarts, and sent twice when it does not. Writing the intent to
    PostgreSQL in the *same transaction* as the booking confirmation means the
    work exists if and only if the booking does; a worker then performs it
    with retries.

    Redis is the broker for scheduling, never the record — this table is.
    """

    __tablename__ = "outbox_messages"

    topic: Mapped[str] = mapped_column(String(80), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    status: Mapped[OutboxStatus] = mapped_column(
        outbox_status_enum, nullable=False, default=OutboxStatus.PENDING
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=8)

    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_by: Mapped[str | None] = mapped_column(String(80))

    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)

    # Lets a producer enqueue "exactly one of these", e.g. one confirmation
    # email per booking however many times the path is retried.
    dedup_key: Mapped[str | None] = mapped_column(String(160))

    __table_args__ = (
        UniqueConstraint("dedup_key", name="uq_outbox_messages_dedup_key"),
        CheckConstraint("attempts >= 0", name="attempts_not_negative"),
        CheckConstraint("max_attempts > 0", name="max_attempts_positive"),
        # The worker's claim query: due, runnable work, oldest first.
        Index(
            "ix_outbox_messages_claimable",
            "available_at",
            postgresql_where="status IN ('PENDING', 'PROCESSING')",
        ),
        Index("ix_outbox_messages_topic_status", "topic", "status"),
    )
