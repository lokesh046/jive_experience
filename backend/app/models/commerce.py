"""Commerce: reservations, bookings, payments and refunds.

One module because these records are written together inside the same
transactions and share a lifecycle. Splitting them would scatter the
invariants that keep money and inventory consistent.

The money rule throughout: integer paise, never a float.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

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
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, money_column

# --------------------------------------------------------------- enums ---


class ReservationStatus(StrEnum):
    HELD = "HELD"
    CONVERTED = "CONVERTED"
    EXPIRED = "EXPIRED"
    RELEASED = "RELEASED"


class BookingSource(StrEnum):
    """How a booking came to exist."""

    ONLINE = "ONLINE"  # bought through the website and paid through the gateway
    COMPLIMENTARY = "COMPLIMENTARY"  # issued free by an administrator
    CASH = "CASH"  # paid in cash and recorded by an administrator


class BookingStatus(StrEnum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
    REFUNDED = "REFUNDED"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"


class PaymentStatus(StrEnum):
    CREATED = "CREATED"
    PENDING = "PENDING"
    AUTHORIZED = "AUTHORIZED"
    CAPTURED = "CAPTURED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    REFUNDED = "REFUNDED"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"


class RefundStatus(StrEnum):
    REQUESTED = "REQUESTED"
    PROCESSING = "PROCESSING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class RefundReason(StrEnum):
    CUSTOMER_CANCELLED = "CUSTOMER_CANCELLED"
    ADMIN_CANCELLED = "ADMIN_CANCELLED"
    EVENT_CANCELLED = "EVENT_CANCELLED"
    INVENTORY_UNAVAILABLE = "INVENTORY_UNAVAILABLE"
    PAYMENT_INCONSISTENCY = "PAYMENT_INCONSISTENCY"


def _pg_enum(enum_cls: type[StrEnum], name: str) -> Enum:
    return Enum(enum_cls, name=name, values_callable=lambda e: [member.value for member in e])


reservation_status_enum = _pg_enum(ReservationStatus, "reservation_status")
booking_status_enum = _pg_enum(BookingStatus, "booking_status")
booking_source_enum = _pg_enum(BookingSource, "booking_source")
payment_status_enum = _pg_enum(PaymentStatus, "payment_status")
refund_status_enum = _pg_enum(RefundStatus, "refund_status")
refund_reason_enum = _pg_enum(RefundReason, "refund_reason")


# -------------------------------------------------------- reservations ---


class TicketReservation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A short-lived hold on inventory while the customer pays.

    The held quantity is added to `ticket_categories.reserved_count` in the
    same transaction that creates this row, and subtracted again exactly once
    when the hold is converted, expires or is released. The status transition
    is what makes release idempotent: a sweeper that runs twice moves the row
    HELD → EXPIRED once and does nothing the second time.
    """

    __tablename__ = "ticket_reservations"

    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("events.id", ondelete="CASCADE"), nullable=False
    )
    ticket_category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ticket_categories.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    booking_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bookings.id", ondelete="SET NULL")
    )

    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[ReservationStatus] = mapped_column(
        reservation_status_enum, nullable=False, default=ReservationStatus.HELD
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("quantity > 0", name="quantity_positive"),
        # The sweeper's query: live holds past their expiry.
        Index(
            "ix_ticket_reservations_expiry_sweep",
            "expires_at",
            postgresql_where="status = 'HELD'",
        ),
        Index("ix_ticket_reservations_category_status", "ticket_category_id", "status"),
        Index("ix_ticket_reservations_user_id", "user_id"),
        Index("ix_ticket_reservations_booking_id", "booking_id"),
    )


# ------------------------------------------------------------ bookings ---


class Booking(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A purchase. Prices are always computed server-side."""

    __tablename__ = "bookings"

    reference: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("events.id", ondelete="RESTRICT"), nullable=False
    )

    status: Mapped[BookingStatus] = mapped_column(
        booking_status_enum, nullable=False, default=BookingStatus.PENDING
    )

    subtotal_paise: Mapped[int] = money_column(default=0)
    fees_paise: Mapped[int] = money_column(default=0)
    # What a promo code took off the subtotal. The total is subtotal + fees - discount.
    discount_paise: Mapped[int] = money_column(default=0, server_default="0")
    total_paise: Mapped[int] = money_column(default=0)
    refunded_paise: Mapped[int] = money_column(default=0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")

    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Supplied by the client so a retried "create booking" returns the first
    # booking instead of making a second one.
    idempotency_key: Mapped[str | None] = mapped_column(String(80))

    # A pending booking that is never paid for expires with its reservations.
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancellation_reason: Mapped[str | None] = mapped_column(String(500))

    customer_note: Mapped[str | None] = mapped_column(Text)

    promo_code_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("promo_codes.id", ondelete="SET NULL")
    )

    source: Mapped[BookingSource] = mapped_column(
        booking_source_enum,
        nullable=False,
        default=BookingSource.ONLINE,
        server_default=BookingSource.ONLINE.value,
    )
    # Who recorded it, for bookings that were not made online.
    issued_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    items: Mapped[list[BookingItem]] = relationship(
        back_populates="booking", cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key", name="uq_bookings_user_id_idempotency_key"),
        CheckConstraint("subtotal_paise >= 0", name="subtotal_not_negative"),
        CheckConstraint("fees_paise >= 0", name="fees_not_negative"),
        CheckConstraint("total_paise >= 0", name="total_not_negative"),
        CheckConstraint("discount_paise >= 0", name="discount_not_negative"),
        CheckConstraint("discount_paise <= subtotal_paise", name="discount_within_subtotal"),
        CheckConstraint(
            "total_paise = subtotal_paise + fees_paise - discount_paise",
            name="total_is_subtotal_plus_fees_minus_discount",
        ),
        # A refund can never exceed what was taken.
        CheckConstraint(
            "refunded_paise >= 0 AND refunded_paise <= total_paise",
            name="refund_within_total",
        ),
        CheckConstraint("quantity >= 0", name="quantity_not_negative"),
        Index("ix_bookings_user_id_created_at", "user_id", "created_at"),
        Index("ix_bookings_event_id_status", "event_id", "status"),
        Index("ix_bookings_status_expires_at", "status", "expires_at"),
    )


class BookingItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One ticket category within a booking.

    The category name and unit price are copied here. The price the customer
    paid must remain readable years later even if the category is renamed,
    repriced or deleted.
    """

    __tablename__ = "booking_items"

    booking_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bookings.id", ondelete="CASCADE"), nullable=False
    )
    ticket_category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ticket_categories.id", ondelete="RESTRICT"),
        nullable=False,
    )

    category_name: Mapped[str] = mapped_column(String(120), nullable=False)
    unit_price_paise: Mapped[int] = money_column()
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    line_total_paise: Mapped[int] = money_column()

    booking: Mapped[Booking] = relationship(back_populates="items")

    __table_args__ = (
        UniqueConstraint(
            "booking_id",
            "ticket_category_id",
            name="uq_booking_items_booking_id_ticket_category_id",
        ),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("unit_price_paise >= 0", name="unit_price_not_negative"),
        CheckConstraint(
            "line_total_paise = unit_price_paise * quantity", name="line_total_consistent"
        ),
        Index("ix_booking_items_ticket_category_id", "ticket_category_id"),
    )


# ------------------------------------------------------------ payments ---


class Payment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A payment attempt against a booking.

    Provider-independent: `provider` names which gateway handled it, and the
    two provider identifiers are unique so a duplicate callback or a retried
    order creation cannot produce a second payment record.
    """

    __tablename__ = "payments"

    booking_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bookings.id", ondelete="RESTRICT"), nullable=False
    )

    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    provider_order_id: Mapped[str | None] = mapped_column(String(120))
    provider_payment_id: Mapped[str | None] = mapped_column(String(120))

    amount_paise: Mapped[int] = money_column()
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")

    status: Mapped[PaymentStatus] = mapped_column(
        payment_status_enum, nullable=False, default=PaymentStatus.CREATED
    )

    # Sent to the provider so a retried order creation is not charged twice.
    idempotency_key: Mapped[str] = mapped_column(String(80), nullable=False)

    provider_status: Mapped[str | None] = mapped_column(String(60))
    failure_reason: Mapped[str | None] = mapped_column(String(500))
    method: Mapped[str | None] = mapped_column(String(40))

    authorized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reconciled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        # Never two records for one gateway payment, whatever order the
        # browser redirect and the webhook arrive in.
        UniqueConstraint(
            "provider", "provider_payment_id", name="uq_payments_provider_provider_payment_id"
        ),
        UniqueConstraint(
            "provider", "provider_order_id", name="uq_payments_provider_provider_order_id"
        ),
        UniqueConstraint("idempotency_key", name="uq_payments_idempotency_key"),
        CheckConstraint("amount_paise > 0", name="amount_positive"),
        Index("ix_payments_booking_id", "booking_id"),
        Index("ix_payments_status_created_at", "status", "created_at"),
        # The reconciliation job: payments left in flight.
        Index(
            "ix_payments_pending_reconciliation",
            "created_at",
            postgresql_where="status IN ('CREATED', 'PENDING', 'AUTHORIZED')",
        ),
    )


class PaymentWebhookEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Every webhook the gateway sends, recorded before it is acted on.

    Gateways retry; duplicates are normal, not an error. The unique constraint
    on (provider, provider_event_id) is what makes processing exactly-once —
    a repeat insert fails and the handler returns success without redoing the
    work.
    """

    __tablename__ = "payment_webhook_events"

    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    provider_event_id: Mapped[str] = mapped_column(String(160), nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)

    payment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("payments.id", ondelete="SET NULL")
    )

    signature_verified: Mapped[bool] = mapped_column(nullable=False, default=False)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    source_ip: Mapped[str | None] = mapped_column(INET)

    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processing_error: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint(
            "provider",
            "provider_event_id",
            name="uq_payment_webhook_events_provider_provider_event_id",
        ),
        Index("ix_payment_webhook_events_payment_id", "payment_id"),
        Index(
            "ix_payment_webhook_events_unprocessed",
            "created_at",
            postgresql_where="processed_at IS NULL",
        ),
    )


# ------------------------------------------------------------- refunds ---


class Refund(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A refund request and its progress.

    A gateway accepting a refund does not mean the money has moved, so this is
    a state machine (REQUESTED → PROCESSING → SUCCEEDED | FAILED) reconciled
    on a schedule rather than a boolean.
    """

    __tablename__ = "refunds"

    booking_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bookings.id", ondelete="RESTRICT"), nullable=False
    )
    payment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("payments.id", ondelete="RESTRICT"), nullable=False
    )

    amount_paise: Mapped[int] = money_column()
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")

    status: Mapped[RefundStatus] = mapped_column(
        refund_status_enum, nullable=False, default=RefundStatus.REQUESTED
    )
    reason: Mapped[RefundReason] = mapped_column(refund_reason_enum, nullable=False)
    reason_note: Mapped[str | None] = mapped_column(String(500))

    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    provider_refund_id: Mapped[str | None] = mapped_column(String(120))
    idempotency_key: Mapped[str] = mapped_column(String(80), nullable=False)

    requested_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_reason: Mapped[str | None] = mapped_column(String(500))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_refunds_idempotency_key"),
        UniqueConstraint(
            "provider", "provider_refund_id", name="uq_refunds_provider_provider_refund_id"
        ),
        CheckConstraint("amount_paise > 0", name="amount_positive"),
        Index("ix_refunds_booking_id", "booking_id"),
        Index("ix_refunds_payment_id", "payment_id"),
        Index(
            "ix_refunds_pending_reconciliation",
            "created_at",
            postgresql_where="status IN ('REQUESTED', 'PROCESSING')",
        ),
    )
