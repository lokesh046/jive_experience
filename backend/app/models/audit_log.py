"""Immutable audit trail for sensitive actions.

Written for: event publish/cancel, price and inventory changes, booking and
refund decisions, staff assignment, privileged login, and every manual override
of an automated money flow. Rows are append-only — nothing in the application
updates or deletes them.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.user import user_role_enum


class AuditLog(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "audit_logs"

    # Nullable: system-initiated actions (webhook handlers, scheduled jobs)
    # have no human actor. The actor row is kept on user deletion so the trail
    # survives the account.
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    actor_role: Mapped[str | None] = mapped_column(user_role_enum)
    actor_label: Mapped[str | None] = mapped_column(String(160))

    # Dotted verb, e.g. "event.published", "refund.initiated".
    action: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(60), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(64))

    # Redacted snapshots; never contains secrets, card data or raw tokens.
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    context: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    request_id: Mapped[str | None] = mapped_column(String(64), index=True)
    ip_address: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(String(400))

    __table_args__ = (
        Index("ix_audit_logs_entity", "entity_type", "entity_id"),
        Index("ix_audit_logs_action_created_at", "action", "created_at"),
    )
