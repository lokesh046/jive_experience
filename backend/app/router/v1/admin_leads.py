"""Administrator inbox: enquiries, and the newsletter list."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Response

from app.dependencies import LeadServiceDep, Pagination, RequireAdmin, WaitlistServiceDep
from app.models.lead import EnquiryStatus
from app.schemas.leads import (
    EnquiryOut,
    EnquiryPage,
    EnquiryUpdate,
    SubscriberOut,
    SubscriberPage,
)
from app.schemas.waitlist import WaitlistPage

router = APIRouter(tags=["admin: inbox"])


@router.get("/enquiries", response_model=EnquiryPage, summary="Enquiries, newest first")
async def list_enquiries(
    actor: RequireAdmin,
    service: LeadServiceDep,
    pagination: Pagination,
    enquiry_status: Annotated[EnquiryStatus | None, Query(alias="status")] = None,
) -> EnquiryPage:
    rows, total, counts = await service.list_enquiries(pagination, status=enquiry_status)
    return EnquiryPage(
        items=[EnquiryOut.model_validate(r) for r in rows],
        total=total,
        page=pagination.page,
        size=pagination.size,
        counts=counts,
    )


@router.patch("/enquiries/{enquiry_id}", response_model=EnquiryOut, summary="Update an enquiry")
async def update_enquiry(
    enquiry_id: uuid.UUID, payload: EnquiryUpdate, actor: RequireAdmin, service: LeadServiceDep
) -> EnquiryOut:
    return EnquiryOut.model_validate(await service.update_enquiry(enquiry_id, payload, actor=actor))


@router.get("/subscribers", response_model=SubscriberPage, summary="Newsletter subscribers")
async def list_subscribers(
    actor: RequireAdmin,
    service: LeadServiceDep,
    pagination: Pagination,
    search: Annotated[str | None, Query(max_length=80)] = None,
) -> SubscriberPage:
    rows, total, active = await service.list_subscribers(pagination, search=search)
    return SubscriberPage(
        items=[SubscriberOut.model_validate(r) for r in rows],
        total=total,
        page=pagination.page,
        size=pagination.size,
        active=active,
    )


@router.get(
    "/subscribers.csv",
    summary="Download the subscribed addresses",
    response_class=Response,
    responses={200: {"content": {"text/csv": {}}}},
)
async def subscribers_csv(actor: RequireAdmin, service: LeadServiceDep) -> Response:
    body = await service.subscribers_csv(actor=actor)
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="newsletter-subscribers.csv"',
            "Cache-Control": "no-store",
        },
    )


@router.get(
    "/events/{event_id}/waitlist",
    response_model=WaitlistPage,
    summary="Who is waiting for tickets to an event",
)
async def event_waitlist(
    event_id: uuid.UUID,
    actor: RequireAdmin,
    service: WaitlistServiceDep,
    pagination: Pagination,
) -> WaitlistPage:
    rows, total, counts = await service.list_for_event(event_id, pagination)
    return WaitlistPage(
        items=rows,
        total=total,
        page=pagination.page,
        size=pagination.size,
        waiting=counts.get("WAITING", 0),
        notified=counts.get("NOTIFIED", 0),
    )
