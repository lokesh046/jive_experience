"""The waitlist: people who want tickets to a sold-out night."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class WaitlistStatus(StrEnum):
    WAITING = "WAITING"
    NOTIFIED = "NOTIFIED"  # told that tickets are available; they still have to buy them
    LEFT = "LEFT"


waitlist_status_enum = Enum(
    WaitlistStatus,
    name="waitlist_status",
    values_callable=lambda e: [m.value for m in e],
    native_enum=True,
    create_type=False,
)


class WaitlistEntry(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "waitlist_entries"

    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("events.id", ondelete="CASCADE"), nullable=False
    )
    # A particular ticket type, or null for "any type".
    ticket_category_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ticket_categories.id", ondelete="SET NULL")
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    status: Mapped[WaitlistStatus] = mapped_column(
        waitlist_status_enum,
        nullable=False,
        default=WaitlistStatus.WAITING,
        server_default=WaitlistStatus.WAITING.value,
    )
    # Lets a person leave from the link in an email without signing in.
    leave_token: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("event_id", "email", name="uq_waitlist_entries_event_id_email"),
        Index("ix_waitlist_entries_event_id_status", "event_id", "status"),
    )
