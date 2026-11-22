"""Leads: private-booking enquiries and newsletter subscribers."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import Boolean, Date, DateTime, Enum, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class EnquiryStatus(StrEnum):
    NEW = "NEW"
    CONTACTED = "CONTACTED"
    CLOSED = "CLOSED"


enquiry_status_enum = Enum(
    EnquiryStatus,
    name="enquiry_status",
    values_callable=lambda e: [m.value for m in e],
    native_enum=True,
    create_type=False,
)


class Enquiry(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Someone asking about a private booking, from the homepage form."""

    __tablename__ = "enquiries"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(30))
    event_date: Mapped[date | None] = mapped_column(Date)
    guests: Mapped[int | None] = mapped_column(Integer)
    message: Mapped[str] = mapped_column(Text, nullable=False)

    status: Mapped[EnquiryStatus] = mapped_column(
        enquiry_status_enum,
        nullable=False,
        default=EnquiryStatus.NEW,
        server_default=EnquiryStatus.NEW.value,
    )
    admin_note: Mapped[str | None] = mapped_column(Text)
    handled_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    __table_args__ = (Index("ix_enquiries_status_created_at", "status", "created_at"),)


class NewsletterSubscriber(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "newsletter_subscribers"

    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    subscribed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    # Lets a person unsubscribe from the link in an email without signing in.
    unsubscribe_token: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    unsubscribed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
