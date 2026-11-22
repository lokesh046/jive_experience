"""Event-staff scanner routes.

Used from a phone browser at the gate, over HTTPS (the camera requires it).
Online only in v1: there is no offline acceptance, because an offline scanner
cannot know whether a ticket was already used at another gate.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter

from app.dependencies import (
    CatalogueServiceDep,
    RequireAdminOrStaff,
    StaffServiceDep,
    TicketServiceDep,
)
from app.schemas.booking import (
    AssignedEventOut,
    AttendanceOut,
    TicketScanRequest,
    TicketScanResponse,
)

router = APIRouter(tags=["scanner"])


@router.get(
    "/events",
    response_model=list[AssignedEventOut],
    summary="Events you are assigned to",
)
async def my_events(
    staff: RequireAdminOrStaff,
    service: StaffServiceDep,
    catalogue: CatalogueServiceDep,
) -> list[AssignedEventOut]:
    """The scanner's event picker — only events this person may work."""
    events = await service.scannable_events(staff)
    return [
        AssignedEventOut(
            event_id=event.id,
            slug=event.slug,
            title=event.title,
            starts_at=event.starts_at,
            ends_at=event.ends_at,
            timezone=event.timezone,
            venue_name=event.venue.name,
            city=event.venue.city,
        )
        for event in events
    ]


@router.post(
    "/scan",
    response_model=TicketScanResponse,
    summary="Scan a ticket QR code",
)
async def scan_ticket(
    payload: TicketScanRequest,
    staff: RequireAdminOrStaff,
    service: TicketServiceDep,
) -> TicketScanResponse:
    """Validate and check in, atomically.

    Always returns 200 with an explicit `result`, including for rejections.
    The person at the gate needs to know *why* a ticket failed — already used,
    wrong event, cancelled, refunded, invalid — and an HTTP error code cannot
    carry that distinction usefully on a phone with poor signal.

    Two simultaneous scans of the same code produce exactly one SUCCESS.
    """
    outcome = await service.scan(
        qr_token=payload.qr_token,
        event_id=payload.event_id,
        staff=staff,
        device_label=payload.device_label,
    )
    ticket = outcome.ticket
    return TicketScanResponse(
        result=outcome.result,
        ok=outcome.ok,
        message=outcome.message,
        ticket_serial=ticket.serial if ticket else None,
        attendee_name=ticket.attendee_name if ticket else None,
        checked_in_at=ticket.checked_in_at if ticket else None,
    )


@router.get(
    "/events/{event_id}/attendance",
    response_model=AttendanceOut,
    summary="Attendance counts for an event",
)
async def attendance(
    event_id: uuid.UUID,
    staff: RequireAdminOrStaff,
    service: TicketServiceDep,
) -> AttendanceOut:
    """Staff see only events they are assigned to; administrators see all."""
    await service.assert_staff_may_view(staff, event_id)
    counts = await service.attendance(event_id)
    return AttendanceOut(
        event_id=event_id,
        issued=counts.get("ISSUED", 0),
        checked_in=counts.get("CHECKED_IN", 0),
        cancelled=counts.get("CANCELLED", 0),
        refunded=counts.get("REFUNDED", 0),
        total=counts.get("TOTAL", 0),
    )
