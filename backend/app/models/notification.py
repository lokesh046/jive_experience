"""In-app notifications and each person's choices about them."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Notification(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One message for one person: shown in their bell, and sometimes also emailed."""

    __tablename__ = "notifications"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # Which thing happened ("booking.tickets_ready") and which group it belongs to ("bookings").
    kind: Mapped[str] = mapped_column(String(60), nullable=False)
    category: Mapped[str] = mapped_column(String(30), nullable=False)
    severity: Mapped[str] = mapped_column(
        String(10), nullable=False, default="info", server_default="info"
    )
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    body: Mapped[str | None] = mapped_column(String(500))
    # A path on this site, never an outside address.
    link: Mapped[str | None] = mapped_column(String(300))
    # The same event never notifies the same person twice.
    dedup_key: Mapped[str | None] = mapped_column(String(160))
    data: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("severity IN ('info', 'warn', 'critical')", name="severity_known"),
        CheckConstraint("link IS NULL OR link LIKE '/%'", name="link_is_a_path"),
        Index("ix_notifications_user_id_created_at", "user_id", "created_at"),
        Index(
            "uq_notifications_user_id_dedup_key",
            "user_id",
            "dedup_key",
            unique=True,
            postgresql_where=text("dedup_key IS NOT NULL"),
        ),
        Index(
            "ix_notifications_unread",
            "user_id",
            postgresql_where=text("read_at IS NULL"),
        ),
    )


class NotificationPreference(Base):
    """A person's switch for one group of notifications on one channel."""

    __tablename__ = "notification_preferences"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    category: Mapped[str] = mapped_column(String(30), primary_key=True)
    channel: Mapped[str] = mapped_column(String(10), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)

    __table_args__ = (
        CheckConstraint("channel IN ('in_app', 'email', 'push')", name="channel_known"),
    )
