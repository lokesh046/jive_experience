"""Promo codes: a discount a customer enters at checkout."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class PromoDiscountType(StrEnum):
    PERCENT = "PERCENT"
    FIXED = "FIXED"


promo_discount_type_enum = Enum(
    PromoDiscountType,
    name="promo_discount_type",
    values_callable=lambda e: [m.value for m in e],
    native_enum=True,
    create_type=False,
)


class PromoCode(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The discount itself is fixed at creation: change a code's value by making a new code,
    so two customers never see different terms under the same name."""

    __tablename__ = "promo_codes"

    code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(String(200))

    discount_type: Mapped[PromoDiscountType] = mapped_column(
        promo_discount_type_enum, nullable=False
    )
    percent_off: Mapped[int | None] = mapped_column(Integer)
    amount_off_paise: Mapped[int | None] = mapped_column(BigInteger)

    # One event, or null for every event.
    event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("events.id", ondelete="CASCADE")
    )

    max_uses: Mapped[int | None] = mapped_column(Integer)
    used_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    max_uses_per_customer: Mapped[int | None] = mapped_column(
        Integer, default=1, server_default="1"
    )
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    __table_args__ = (
        CheckConstraint(
            "(discount_type = 'PERCENT' AND percent_off BETWEEN 1 AND 100 "
            "AND amount_off_paise IS NULL) OR "
            "(discount_type = 'FIXED' AND amount_off_paise > 0 AND percent_off IS NULL)",
            name="discount_matches_type",
        ),
        CheckConstraint("used_count >= 0", name="used_count_not_negative"),
        CheckConstraint("max_uses IS NULL OR used_count <= max_uses", name="used_within_max"),
        CheckConstraint(
            "max_uses_per_customer IS NULL OR max_uses_per_customer >= 1",
            name="per_customer_positive",
        ),
        CheckConstraint(
            "valid_until IS NULL OR valid_from IS NULL OR valid_until > valid_from",
            name="window_ordered",
        ),
    )
