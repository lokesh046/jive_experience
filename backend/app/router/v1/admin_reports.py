"""Administrator sales reports."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Response

from app.core.pagination import Page
from app.dependencies import Pagination, ReportServiceDep, RequireAdmin
from app.models.fulfilment import TicketStatus
from app.schemas.reports import AttendeeOut, SalesReport, ScanOut

router = APIRouter(tags=["admin: reports"])


@router.get("/reports/sales", response_model=SalesReport, summary="Sales report")
async def sales_report(
    actor: RequireAdmin,
    service: ReportServiceDep,
    days: Annotated[int, Query(ge=7, le=365, description="Length of the daily chart")] = 30,
    event_id: Annotated[uuid.UUID | None, Query()] = None,
) -> SalesReport:
    """Revenue, tickets, refunds and check-ins per event, plus sales by day.

    With `event_id` the report is for that one event and adds a breakdown by
    ticket category. Money is in paise.
    """
    return await service.sales(days=days, event_id=event_id)


@router.get(
    "/events/{event_id}/attendees",
    response_model=Page[AttendeeOut],
    summary="Who holds a ticket for an event",
)
async def attendees(
    event_id: uuid.UUID,
    actor: RequireAdmin,
    service: ReportServiceDep,
    pagination: Pagination,
    ticket_status: Annotated[TicketStatus | None, Query(alias="status")] = None,
    search: Annotated[str | None, Query(max_length=80)] = None,
) -> Page[AttendeeOut]:
    items, total = await service.attendees(
        event_id, pagination, status=ticket_status, search=search
    )
    return Page.build(items, total=total, params=pagination)


@router.get(
    "/events/{event_id}/attendees.csv",
    summary="Download the attendee list as a spreadsheet",
    response_class=Response,
    responses={200: {"content": {"text/csv": {}}}},
)
async def attendees_csv(
    event_id: uuid.UUID, actor: RequireAdmin, service: ReportServiceDep
) -> Response:
    filename, body = await service.attendees_csv(event_id, actor=actor)
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


@router.get(
    "/events/{event_id}/scans",
    response_model=Page[ScanOut],
    summary="Every scan at the gate, newest first, failures included",
)
async def scans(
    event_id: uuid.UUID, actor: RequireAdmin, service: ReportServiceDep, pagination: Pagination
) -> Page[ScanOut]:
    items, total = await service.scans(event_id, pagination)
    return Page.build(items, total=total, params=pagination)
