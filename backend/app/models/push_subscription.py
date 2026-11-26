"""A browser that has agreed to receive push notifications for one person."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class PushSubscription(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "push_subscriptions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # The browser's own address for this device. Unique: one row per device, whoever signed in.
    endpoint: Mapped[str] = mapped_column(String(1024), nullable=False, unique=True)
    # The device's public key and auth secret: what we encrypt each message with.
    p256dh: Mapped[str] = mapped_column(String(200), nullable=False)
    auth: Mapped[str] = mapped_column(String(100), nullable=False)
    # "webpush" for a browser, "expo" for the phone app (endpoint holds the Expo push token).
    provider: Mapped[str] = mapped_column(
        String(20), nullable=False, default="webpush", server_default="webpush"
    )
    user_agent: Mapped[str | None] = mapped_column(String(300))
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Consecutive failures that were not a clear "this device is gone".
    failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    __table_args__ = (Index("ix_push_subscriptions_user_id", "user_id"),)
