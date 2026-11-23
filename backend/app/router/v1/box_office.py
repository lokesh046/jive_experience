"""Counter sales: tickets sold in person, paid in cash or through the gateway.

Open to administrators and to staff assigned to the event. A seller can only see
and finish their own sales; an administrator can see all of them.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from app.core.errors import NotFoundError
from app.dependencies import (
    BookingServiceDep,
    PaymentServiceDep,
    RequireAdminOrStaff,
    TicketServiceDep,
)
from app.models.commerce import BookingSource
from app.models.user import UserRole
from app.repositories.user import UserRepository
from app.schemas.booking import (
    BookingOut,
    BoxOfficeBookingOut,
    BoxOfficeSaleRequest,
    BoxOfficeSellerRow,
    CheckoutResponse,
    CheckoutVerifyRequest,
)

router = APIRouter(tags=["box office"])


@router.post(
    "/events/{event_id}/sales",
    response_model=BookingOut,
    status_code=status.HTTP_201_CREATED,
    summary="Start a counter sale",
)
async def start_sale(
    event_id: uuid.UUID,
    payload: BoxOfficeSaleRequest,
    seller: RequireAdminOrStaff,
    bookings: BookingServiceDep,
    tickets: TicketServiceDep,
) -> BookingOut:
    """Cash is confirmed at once. Online leaves a pending booking to pay at the counter."""
    await tickets.assert_staff_may_view(seller, event_id)
    booking = await bookings.box_office_sale(event_id, payload, actor=seller)
    return BookingOut.model_validate(booking)


@router.get(
    "/bookings/{reference}",
    response_model=BoxOfficeBookingOut,
    summary="A counter sale and its tickets",
)
async def get_sale(
    reference: str,
    seller: RequireAdminOrStaff,
    bookings: BookingServiceDep,
    tickets: TicketServiceDep,
) -> BoxOfficeBookingOut:
    booking = await bookings.get_for_seller(reference, seller)
    rows = await tickets.tickets.for_booking(booking.id)
    return BoxOfficeBookingOut(
        booking=BookingOut.model_validate(booking),
        tickets=[tickets.to_schema(t) for t in rows],
    )


@router.post(
    "/bookings/{reference}/checkout",
    response_model=CheckoutResponse,
    summary="Open the payment window for a counter sale",
)
async def start_checkout(
    reference: str,
    seller: RequireAdminOrStaff,
    bookings: BookingServiceDep,
    payments: PaymentServiceDep,
) -> CheckoutResponse:
    booking = await bookings.get_for_seller(reference, seller)
    buyer = await UserRepository(bookings.session).get(booking.user_id)
    if buyer is None or booking.source is not BookingSource.ONLINE:
        raise NotFoundError("Booking not found.", code="BOOKING_NOT_FOUND")
    order = await payments.start_checkout(booking, customer=buyer)
    return CheckoutResponse(
        provider=order.provider,
        provider_order_id=order.provider_order_id,
        amount_paise=order.amount_paise,
        currency=order.currency,
        booking_reference=booking.reference,
        checkout_payload=order.checkout_payload,
    )


@router.post(
    "/bookings/{reference}/verify",
    response_model=BookingOut,
    summary="Confirm a counter sale after the payment window",
)
async def verify_checkout(
    reference: str,
    payload: CheckoutVerifyRequest,
    seller: RequireAdminOrStaff,
    bookings: BookingServiceDep,
    payments: PaymentServiceDep,
) -> BookingOut:
    """The provider is asked directly, as on the website. Safe to race with the webhook."""
    booking = await bookings.get_for_seller(reference, seller)
    buyer = await UserRepository(bookings.session).get(booking.user_id)
    if buyer is None:
        raise NotFoundError("Booking not found.", code="BOOKING_NOT_FOUND")
    confirmed = await payments.verify_checkout(
        payload.provider_payment_id,
        customer=buyer,
        provider_order_id=payload.provider_order_id,
        signature=payload.signature,
    )
    if confirmed.reference != reference:
        raise NotFoundError("Booking not found.", code="BOOKING_NOT_FOUND")
    return BookingOut.model_validate(confirmed)


@router.get(
    "/events/{event_id}/summary",
    response_model=list[BoxOfficeSellerRow],
    summary="Counter sales per seller",
)
async def summary(
    event_id: uuid.UUID,
    seller: RequireAdminOrStaff,
    bookings: BookingServiceDep,
    tickets: TicketServiceDep,
) -> list[BoxOfficeSellerRow]:
    """Cash to hand in and online takings, for each seller. Staff see only their own."""
    await tickets.assert_staff_may_view(seller, event_id)
    only = None if seller.role is UserRole.ADMIN else seller.id
    rows = await bookings.bookings.box_office_totals(event_id, seller_id=only)
    out: dict[uuid.UUID, BoxOfficeSellerRow] = {}
    for seller_id, name, source, count, paise in rows:
        if seller_id is None:
            continue
        row = out.setdefault(
            seller_id,
            BoxOfficeSellerRow(
                seller_id=seller_id,
                seller_name=name,
                cash_tickets=0,
                cash_paise=0,
                online_tickets=0,
                online_paise=0,
            ),
        )
        if source == BookingSource.CASH.value:
            row.cash_tickets, row.cash_paise = count, paise
        else:
            row.online_tickets, row.online_paise = count, paise
    return list(out.values())
