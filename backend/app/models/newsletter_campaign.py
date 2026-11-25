"""Newsletters an administrator writes and sends to the subscriber list."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class CampaignStatus(StrEnum):
    DRAFT = "DRAFT"
    SENT = "SENT"  # queued to everyone; delivery progress is counted separately


class NewsletterCampaign(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "newsletter_campaigns"

    subject: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    # An optional night to feature: the email shows its photo, date and venue, with a link.
    event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("events.id", ondelete="SET NULL")
    )
    button_label: Mapped[str | None] = mapped_column(String(60))
    button_url: Mapped[str | None] = mapped_column(String(500))

    status: Mapped[str] = mapped_column(
        String(12), nullable=False, default=CampaignStatus.DRAFT.value, server_default="DRAFT"
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # How many subscribers it was queued to, fixed at the moment of sending.
    recipients: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # Counted by the worker as each email goes out.
    delivered: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    __table_args__ = (
        CheckConstraint("status IN ('DRAFT', 'SENT')", name="status_known"),
        CheckConstraint("char_length(btrim(subject)) > 0", name="subject_not_blank"),
        CheckConstraint("char_length(btrim(body)) > 0", name="body_not_blank"),
    )
