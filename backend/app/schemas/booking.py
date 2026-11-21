"""Booking, payment, refund and ticket contracts.

Note what the request shapes do **not** accept: prices, totals, statuses.
Those are computed server-side from the database. A client-supplied amount is
never anything but a thing to reject.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, Field

from app.models.commerce import BookingStatus, PaymentStatus, RefundReason, RefundStatus
from app.models.fulfilment import CheckinResult, TicketStatus

# ----------------------------------------------------------------- booking ---


class BookingItemRequest(BaseModel):
    ticket_category_id: uuid.UUID
    quantity: Annotated[int, Field(ge=1, le=50)]


class BookingCreateRequest(BaseModel):
    event_slug: Annotated[str, Field(min_length=1, max_length=160)]
    items: Annotated[list[BookingItemRequest], Field(min_length=1, max_length=10)]
    customer_note: Annotated[str | None, Field(default=None, max_length=500)] = None
    # Supplied by the client so a retried request returns the first booking
    # rather than holding the tickets twice.
    idempotency_key: Annotated[str | None, Field(default=None, max_length=80)] = None


class BookingItemOut(BaseModel):
    ticket_category_id: uuid.UUID
    category_name: str
    unit_price_paise: int
    quantity: int
    line_total_paise: int

    model_config = {"from_attributes": True}


class BookingOut(BaseModel):
    id: uuid.UUID
    reference: str
    event_id: uuid.UUID
    status: BookingStatus
    quantity: int
    subtotal_paise: int
    fees_paise: int
    total_paise: int
    refunded_paise: int
    currency: str
    expires_at: datetime | None = None
    confirmed_at: datetime | None = None
    cancelled_at: datetime | None = None
    created_at: datetime
    items: list[BookingItemOut] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class BookingAdminOut(BookingOut):
    user_id: uuid.UUID
    cancellation_reason: str | None = None
    customer_note: str | None = None


# ----------------------------------------------------------------- payment ---


class CheckoutResponse(BaseModel):
    """What the frontend needs to open the provider's hosted checkout."""

    provider: str
    provider_order_id: str
    amount_paise: int
    currency: str
    booking_reference: str
    checkout_payload: dict[str, Any] = Field(default_factory=dict)


class CheckoutVerifyRequest(BaseModel):
    """The browser's return from checkout.

    A *hint* that a payment may exist, never proof. The backend asks the
    provider before confirming anything.

    With Razorpay, Checkout.js hands the browser `razorpay_payment_id`,
    `razorpay_order_id` and `razorpay_signature`; send all three and the
    signature is checked before the network call.
    """

    provider_payment_id: Annotated[str, Field(min_length=1, max_length=120)]
    provider_order_id: Annotated[str | None, Field(default=None, max_length=120)] = None
    signature: Annotated[str | None, Field(default=None, max_length=256)] = None


class PaymentOut(BaseModel):
    id: uuid.UUID
    booking_id: uuid.UUID
    provider: str
    provider_order_id: str | None = None
    provider_payment_id: str | None = None
    amount_paise: int
    currency: str
    status: PaymentStatus
    method: str | None = None
    failure_reason: str | None = None
    captured_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ------------------------------------------------------------------ refund ---


class RefundQuoteOut(BaseModel):
    eligible: bool
    amount_paise: int
    percent: int
    reason: str


class BookingCancelRequest(BaseModel):
    reason: Annotated[str | None, Field(default=None, max_length=500)] = None


class RefundCreateRequest(BaseModel):
    """Administrator-initiated refund. Omit the amount for the full balance."""

    amount_paise: Annotated[int | None, Field(default=None, ge=1)] = None
    reason: RefundReason = RefundReason.ADMIN_CANCELLED
    note: Annotated[str | None, Field(default=None, max_length=500)] = None


class RefundOut(BaseModel):
    id: uuid.UUID
    booking_id: uuid.UUID
    payment_id: uuid.UUID
    amount_paise: int
    currency: str
    status: RefundStatus
    reason: RefundReason
    reason_note: str | None = None
    provider_refund_id: str | None = None
    completed_at: datetime | None = None
    failure_reason: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ------------------------------------------------------------------ ticket ---


class TicketOut(BaseModel):
    """A ticket as the customer sees it, including its scannable code.

    `qr_token` is recomputed for each response rather than stored, so it can
    be shown as often as the owner needs — on a new phone, after clearing an
    app, at the gate — while the database still holds only a hash.

    The code is stable for the life of the ticket and stops working the
    moment it is scanned.
    """

    id: uuid.UUID
    qr_token: str | None = Field(
        default=None, description="Scannable code. Valid until the event, single use."
    )
    serial: str
    booking_id: uuid.UUID
    event_id: uuid.UUID
    ticket_category_id: uuid.UUID
    status: TicketStatus
    attendee_name: str | None = None
    issued_at: datetime | None = None
    checked_in_at: datetime | None = None

    model_config = {"from_attributes": True}


class IssuedTicketOut(TicketOut):
    qr_token: str = Field(description="Shown once. Not recoverable afterwards.")


class TicketScanRequest(BaseModel):
    qr_token: Annotated[str, Field(min_length=10, max_length=256)]
    event_id: uuid.UUID
    device_label: Annotated[str | None, Field(default=None, max_length=120)] = None


class TicketScanResponse(BaseModel):
    """Deliberately explicit, because the person at the gate acts on it."""

    result: CheckinResult
    ok: bool
    message: str
    ticket_serial: str | None = None
    ticket_category: str | None = None
    attendee_name: str | None = None
    checked_in_at: datetime | None = None


class AttendanceOut(BaseModel):
    event_id: uuid.UUID
    issued: int = 0
    checked_in: int = 0
    cancelled: int = 0
    refunded: int = 0
    total: int = 0


# ------------------------------------------------------------------- staff ---


class StaffAssignRequest(BaseModel):
    user_id: uuid.UUID


class StaffAssignmentOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    event_id: uuid.UUID
    full_name: str | None = None
    email: str | None = None
    created_at: datetime


class AssignedEventOut(BaseModel):
    """The scanner's event picker."""

    event_id: uuid.UUID
    slug: str
    title: str
    starts_at: datetime
    venue_name: str
    city: str
