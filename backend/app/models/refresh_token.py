"""Authentication state that must survive a restart: refresh tokens.

Access tokens are short-lived JWTs and are deliberately *not* stored. Refresh
tokens are stored as a SHA-256 hash of the opaque token value, so a database
disclosure does not yield usable sessions.

Rotation: every refresh exchanges the presented token for a new one and marks
the old row as rotated (`replaced_by_id`). If a token that was already rotated
is presented again, the whole chain is treated as compromised and the family is
revoked — this is the standard detection for a stolen refresh token.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import INET, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class TokenRevocationReason(StrEnum):
    LOGOUT = "LOGOUT"
    ROTATED = "ROTATED"
    REUSE_DETECTED = "REUSE_DETECTED"
    ADMIN_REVOKED = "ADMIN_REVOKED"
    PASSWORD_CHANGED = "PASSWORD_CHANGED"
    ACCOUNT_SUSPENDED = "ACCOUNT_SUSPENDED"


revocation_reason_enum = Enum(
    TokenRevocationReason,
    name="token_revocation_reason",
    values_callable=lambda enum: [member.value for member in enum],
)


class RefreshToken(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "refresh_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # SHA-256 hex digest of the opaque token. The token itself is never stored.
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)

    # Identifies a rotation chain descending from one login, so that reuse
    # detection can revoke every descendant in a single statement.
    family_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)

    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revocation_reason: Mapped[TokenRevocationReason | None] = mapped_column(revocation_reason_enum)
    replaced_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("refresh_tokens.id", ondelete="SET NULL")
    )

    # Context captured at issue time, for the session list and audit trail.
    user_agent: Mapped[str | None] = mapped_column(String(400))
    ip_address: Mapped[str | None] = mapped_column(INET)

    __table_args__ = (
        Index("ix_refresh_tokens_user_id_revoked_at", "user_id", "revoked_at"),
        Index("ix_refresh_tokens_expires_at", "expires_at"),
    )

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None
