"""Administrator booking, refund and staff-assignment routes."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.core.pagination import Page
from app.dependencies import (
    BookingServiceDep,
    Pagination,
    RefundServiceDep,
    RequireAdmin,
    StaffServiceDep,
    TicketServiceDep,
)
from app.models.commerce import BookingStatus
from app.schemas.booking import (
    AttendanceOut,
    BookingAdminOut,
    BookingCancelRequest,
    ManualTicketRequest,
    RefundCreateRequest,
    RefundOut,
    StaffAssignmentOut,
    StaffAssignRequest,
)

router = APIRouter(tags=["admin: commerce"])


# ---------------------------------------------------------------- bookings ---


@router.get("/bookings", response_model=Page[BookingAdminOut], summary="Search bookings")
async def list_bookings(
    actor: RequireAdmin,
    service: BookingServiceDep,
    pagination: Pagination,
    event_id: Annotated[uuid.UUID | None, Query()] = None,
    booking_status: Annotated[BookingStatus | None, Query(alias="status")] = None,
    reference: Annotated[str | None, Query(max_length=20)] = None,
) -> Page[BookingAdminOut]:
    rows, total = await service.list_admin(
        pagination, event_id=event_id, status=booking_status, reference=reference
    )
    return Page.build(
        [BookingAdminOut.model_validate(row) for row in rows],
        total=total,
        params=pagination,
    )


@router.get(
    "/bookings/{booking_id}",
    response_model=BookingAdminOut,
    summary="Booking detail",
)
async def booking_detail(
    booking_id: uuid.UUID, actor: RequireAdmin, service: BookingServiceDep
) -> BookingAdminOut:
    return BookingAdminOut.model_validate(await service.get_admin(booking_id))


@router.post(
    "/bookings/{booking_id}/cancel",
    response_model=BookingAdminOut,
    summary="Cancel a booking and refund it",
)
async def cancel_booking(
    booking_id: uuid.UUID,
    payload: BookingCancelRequest,
    actor: RequireAdmin,
    bookings: BookingServiceDep,
    refunds: RefundServiceDep,
) -> BookingAdminOut:
    """Administrator cancellation refunds the full remaining balance.

    The per-event cancellation tiers apply to *customer* cancellations; an
    operator cancelling on the company's behalf is not the customer's fault.
    """
    booking = await bookings.get_admin(booking_id)
    event = await bookings.event_for(booking)
    await refunds.cancel_booking(
        booking=booking, event=event, actor=actor, customer_initiated=False
    )
    return BookingAdminOut.model_validate(booking)


# ----------------------------------------------------------------- refunds ---


@router.post(
    "/bookings/{booking_id}/refunds",
    response_model=RefundOut,
    status_code=status.HTTP_201_CREATED,
    summary="Request a refund against a booking",
)
async def create_refund(
    booking_id: uuid.UUID,
    payload: RefundCreateRequest,
    actor: RequireAdmin,
    bookings: BookingServiceDep,
    refunds: RefundServiceDep,
) -> RefundOut:
    """Records the request; the worker sends it to the provider.

    Omit `amount_paise` for the full remaining balance. The money has not
    moved when this returns — the refund is REQUESTED, and reconciliation
    settles it.
    """
    booking = await bookings.get_admin(booking_id)
    refund = await refunds.request_refund(
        booking=booking,
        amount_paise=payload.amount_paise,
        reason=payload.reason,
        actor=actor,
        note=payload.note,
    )
    return RefundOut.model_validate(refund)


@router.get(
    "/bookings/{booking_id}/refunds",
    response_model=list[RefundOut],
    summary="Refunds against a booking",
)
async def list_refunds(
    booking_id: uuid.UUID, actor: RequireAdmin, refunds: RefundServiceDep
) -> list[RefundOut]:
    rows = await refunds.for_booking(booking_id)
    return [RefundOut.model_validate(row) for row in rows]


# ------------------------------------------------------- staff assignments ---


@router.get(
    "/events/{event_id}/staff",
    response_model=list[StaffAssignmentOut],
    summary="Staff assigned to an event",
)
async def event_staff(
    event_id: uuid.UUID, actor: RequireAdmin, service: StaffServiceDep
) -> list[StaffAssignmentOut]:
    assignments = await service.for_event(event_id)
    return [
        StaffAssignmentOut(
            id=assignment.id,
            user_id=assignment.user_id,
            event_id=assignment.event_id,
            full_name=assignment.user.full_name,
            email=assignment.user.email,
            created_at=assignment.created_at,
        )
        for assignment in assignments
    ]


@router.post(
    "/events/{event_id}/staff",
    response_model=StaffAssignmentOut,
    status_code=status.HTTP_201_CREATED,
    summary="Assign staff to an event",
)
async def assign_staff(
    event_id: uuid.UUID,
    payload: StaffAssignRequest,
    actor: RequireAdmin,
    service: StaffServiceDep,
) -> StaffAssignmentOut:
    """Assignment, not role, is what authorises a scan at this event."""
    assignment = await service.assign(user_id=payload.user_id, event_id=event_id, actor=actor)
    return StaffAssignmentOut(
        id=assignment.id,
        user_id=assignment.user_id,
        event_id=assignment.event_id,
        full_name=assignment.user.full_name,
        email=assignment.user.email,
        created_at=assignment.created_at,
    )


@router.delete(
    "/events/{event_id}/staff/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a staff assignment",
)
async def unassign_staff(
    event_id: uuid.UUID,
    user_id: uuid.UUID,
    actor: RequireAdmin,
    service: StaffServiceDep,
) -> None:
    await service.revoke(user_id=user_id, event_id=event_id, actor=actor)


@router.get(
    "/events/{event_id}/attendance",
    response_model=AttendanceOut,
    summary="Attendance for an event",
)
async def attendance(
    event_id: uuid.UUID, actor: RequireAdmin, service: TicketServiceDep
) -> AttendanceOut:
    counts = await service.attendance(event_id)
    return AttendanceOut(
        event_id=event_id,
        issued=counts.get("ISSUED", 0),
        checked_in=counts.get("CHECKED_IN", 0),
        cancelled=counts.get("CANCELLED", 0),
        refunded=counts.get("REFUNDED", 0),
        total=counts.get("TOTAL", 0),
    )


@router.post(
    "/events/{event_id}/manual-tickets",
    response_model=BookingAdminOut,
    status_code=status.HTTP_201_CREATED,
    summary="Issue complimentary or cash-paid tickets",
)
async def issue_manual_tickets(
    event_id: uuid.UUID,
    payload: ManualTicketRequest,
    actor: RequireAdmin,
    service: BookingServiceDep,
) -> BookingAdminOut:
    """For artists, sponsors, press and door sales. The recipient is emailed their QR codes.

    Complimentary tickets are free. Cash records the ticket price as revenue. Both use
    real capacity and show in attendance and sales.
    """
    booking = await service.issue_manually(event_id, payload, actor=actor)
    return BookingAdminOut.model_validate(booking)
