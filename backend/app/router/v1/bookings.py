"""Customer booking, checkout and ticket routes."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response, status

from app.core.errors import NotFoundError
from app.core.pagination import Page
from app.dependencies import (
    BookingServiceDep,
    Pagination,
    PaymentServiceDep,
    RefundServiceDep,
    RequireCustomer,
    TicketServiceDep,
)
from app.schemas.booking import (
    BookingCancelRequest,
    BookingCreateRequest,
    BookingOut,
    CheckoutResponse,
    CheckoutVerifyRequest,
    RefundOut,
    RefundQuoteOut,
    TicketOut,
)

router = APIRouter(tags=["bookings"])


@router.post(
    "",
    response_model=BookingOut,
    status_code=status.HTTP_201_CREATED,
    summary="Hold tickets and open a pending booking",
)
async def create_booking(
    payload: BookingCreateRequest,
    customer: RequireCustomer,
    service: BookingServiceDep,
    response: Response,
) -> BookingOut:
    """Reserves inventory for a few minutes while the customer pays.

    Idempotent on `idempotency_key`: a repeated request returns the original
    booking with 200 instead of holding the tickets twice.
    """
    booking, created = await service.create(payload, customer=customer)
    if not created:
        response.status_code = status.HTTP_200_OK
    return BookingOut.model_validate(booking)


@router.get("", response_model=Page[BookingOut], summary="Your bookings")
async def list_my_bookings(
    customer: RequireCustomer, service: BookingServiceDep, pagination: Pagination
) -> Page[BookingOut]:
    rows, total = await service.for_customer(customer, pagination)
    return Page.build(
        [BookingOut.model_validate(row) for row in rows], total=total, params=pagination
    )


@router.get("/{reference}", response_model=BookingOut, summary="One booking")
async def get_booking(
    reference: str, customer: RequireCustomer, service: BookingServiceDep
) -> BookingOut:
    return BookingOut.model_validate(await service.get_for_customer(reference, customer))


@router.post(
    "/{reference}/checkout",
    response_model=CheckoutResponse,
    summary="Start payment for a booking",
)
async def start_checkout(
    reference: str,
    customer: RequireCustomer,
    bookings: BookingServiceDep,
    payments: PaymentServiceDep,
) -> CheckoutResponse:
    """Creates the provider order and returns what the hosted checkout needs.

    Re-opening checkout returns the same order rather than creating a second
    charge.
    """
    booking = await bookings.get_for_customer(reference, customer)
    order = await payments.start_checkout(booking, customer=customer)
    return CheckoutResponse(
        provider=order.provider,
        provider_order_id=order.provider_order_id,
        amount_paise=order.amount_paise,
        currency=order.currency,
        booking_reference=booking.reference,
        checkout_payload=order.checkout_payload,
    )


@router.post(
    "/{reference}/verify",
    response_model=BookingOut,
    summary="Confirm a booking after returning from checkout",
)
async def verify_checkout(
    reference: str,
    payload: CheckoutVerifyRequest,
    customer: RequireCustomer,
    payments: PaymentServiceDep,
) -> BookingOut:
    """The browser's return is only a hint — the provider is asked directly.

    Safe to call repeatedly, and safe to race with the webhook: whichever
    arrives first confirms, the other is a no-op.
    """
    booking = await payments.verify_checkout(payload.provider_payment_id, customer=customer)
    if booking.reference != reference:
        raise NotFoundError("Booking not found.", code="BOOKING_NOT_FOUND")
    return BookingOut.model_validate(booking)


@router.get(
    "/{reference}/refund-quote",
    response_model=RefundQuoteOut,
    summary="What cancelling would refund",
)
async def refund_quote(
    reference: str,
    customer: RequireCustomer,
    bookings: BookingServiceDep,
    refunds: RefundServiceDep,
) -> RefundQuoteOut:
    """Shown before the customer confirms a cancellation.

    Returns `eligible: false` with a reason when the event has no cancellation
    policy configured — the policy is a client decision, never a default.
    """
    booking = await bookings.get_for_customer(reference, customer)
    event = await bookings.event_for(booking)
    quote = refunds.quote(booking=booking, event=event)
    return RefundQuoteOut(
        eligible=quote.eligible,
        amount_paise=quote.amount_paise,
        percent=quote.percent,
        reason=quote.reason,
    )


@router.post(
    "/{reference}/cancel",
    response_model=BookingOut,
    summary="Cancel a booking and request the eligible refund",
)
async def cancel_booking(
    reference: str,
    payload: BookingCancelRequest,
    customer: RequireCustomer,
    bookings: BookingServiceDep,
    refunds: RefundServiceDep,
) -> BookingOut:
    booking = await bookings.get_for_customer(reference, customer)
    event = await bookings.event_for(booking)
    await refunds.cancel_booking(
        booking=booking, event=event, actor=customer, customer_initiated=True
    )
    return BookingOut.model_validate(booking)


@router.get(
    "/{reference}/tickets",
    response_model=list[TicketOut],
    summary="QR tickets for a booking",
)
async def booking_tickets(
    reference: str,
    customer: RequireCustomer,
    bookings: BookingServiceDep,
    tickets: TicketServiceDep,
) -> list[TicketOut]:
    """The QR token itself is not returned here.

    It is stored hashed and shown once at issue time; this endpoint returns
    the ticket records so the client can render or re-request them.
    """
    booking = await bookings.get_for_customer(reference, customer)
    rows = await tickets.for_booking(booking, customer=customer)
    return [TicketOut.model_validate(row) for row in rows]


@router.get(
    "/{reference}/refunds",
    response_model=list[RefundOut],
    summary="Refunds against a booking",
)
async def booking_refunds(
    reference: str,
    customer: RequireCustomer,
    bookings: BookingServiceDep,
    refunds: RefundServiceDep,
) -> list[RefundOut]:
    booking = await bookings.get_for_customer(reference, customer)
    rows = await refunds.for_booking(booking.id)
    return [RefundOut.model_validate(row) for row in rows]


tickets_router = APIRouter(tags=["tickets"])


@tickets_router.get("", response_model=Page[TicketOut], summary="All of your tickets")
async def my_tickets(
    customer: RequireCustomer, service: TicketServiceDep, pagination: Pagination
) -> Page[TicketOut]:
    rows, total = await service.for_customer(customer, pagination)
    return Page.build(
        [TicketOut.model_validate(row) for row in rows], total=total, params=pagination
    )


webhook_router = APIRouter(tags=["payments"])


@webhook_router.post(
    "/webhook",
    status_code=status.HTTP_200_OK,
    summary="Payment provider webhook",
)
async def payment_webhook(request: Request, payments: PaymentServiceDep) -> dict[str, str]:
    """Signature-verified, deduplicated, idempotent.

    The raw body is read before parsing because signature verification is
    computed over the exact bytes the provider sent — re-serialising parsed
    JSON would change them and every signature would fail.

    Always answers 200 for a duplicate: providers retry on anything else, and
    a duplicate is routine, not an error.
    """
    body = await request.body()
    headers = {key.lower(): value for key, value in request.headers.items()}
    source_ip = request.client.host if request.client else None
    outcome = await payments.handle_webhook(body=body, headers=headers, source_ip=source_ip)
    return {"status": outcome}
