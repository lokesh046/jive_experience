"""SQLAlchemy declarative base, naming conventions and shared mixins."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, MetaData, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Deterministic constraint names. Without this Alembic generates anonymous
# names that differ between autogenerate runs, which makes migrations that
# DROP a constraint impossible to write reliably.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        pk = getattr(self, "id", None)
        return f"<{type(self).__name__} id={pk}>"


class UUIDPrimaryKeyMixin:
    """UUID primary keys.

    UUIDs are used instead of sequential integers because booking, ticket and
    payment identifiers appear in URLs, QR payload lookups and gateway
    metadata; sequential ids would leak sales volume and invite enumeration.
    """

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )


class TimestampMixin:
    """Creation/modification timestamps, always stored in UTC."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


def money_column(**kwargs: Any) -> Mapped[int]:
    """A money amount in **minor units** (paise).

    BIGINT, never a floating point type and never NUMERIC-as-float. See
    `app.core.money` for the conversion helpers. Keeping one representation
    end to end is what makes refund totals reconcile exactly against captured
    totals.
    """
    return mapped_column(BigInteger, nullable=False, **kwargs)


def utc_now() -> datetime:
    """Timezone-aware current UTC time (never `datetime.utcnow()`)."""
    from datetime import UTC

    return datetime.now(UTC)
