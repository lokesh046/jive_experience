"""Administrator catalogue routes: venues, events and ticket categories.

Every route is administrator-only, stated in the dependency rather than in a
comment.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.core.pagination import Page
from app.dependencies import (
    CatalogueServiceDep,
    OutboxServiceDep,
    Pagination,
    RequireAdmin,
)
from app.schemas.catalogue import (
    EventAdminDetail,
    EventCancelRequest,
    EventCreate,
    EventUpdate,
    TicketCategoryAdmin,
    TicketCategoryCreate,
    TicketCategoryUpdate,
    VenueCreate,
    VenueOut,
    VenueUpdate,
)

router = APIRouter(tags=["admin: catalogue"])


# ------------------------------------------------------------------ venues ---


@router.get("/venues", response_model=Page[VenueOut], summary="List venues")
async def list_venues(
    actor: RequireAdmin, service: CatalogueServiceDep, pagination: Pagination
) -> Page[VenueOut]:
    rows, total = await service.list_venues(pagination)
    return Page.build(
        [VenueOut.model_validate(row) for row in rows], total=total, params=pagination
    )


@router.post(
    "/venues",
    response_model=VenueOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a venue",
)
async def create_venue(
    payload: VenueCreate, actor: RequireAdmin, service: CatalogueServiceDep
) -> VenueOut:
    return VenueOut.model_validate(await service.create_venue(payload, actor=actor))


@router.patch("/venues/{venue_id}", response_model=VenueOut, summary="Update a venue")
async def update_venue(
    venue_id: uuid.UUID,
    payload: VenueUpdate,
    actor: RequireAdmin,
    service: CatalogueServiceDep,
) -> VenueOut:
    return VenueOut.model_validate(await service.update_venue(venue_id, payload, actor=actor))


# ------------------------------------------------------------------ events ---


@router.get("/events", response_model=Page[EventAdminDetail], summary="List all events")
async def list_events(
    actor: RequireAdmin,
    service: CatalogueServiceDep,
    pagination: Pagination,
    event_status: Annotated[str | None, Query(alias="status")] = None,
    search: Annotated[str | None, Query(max_length=120)] = None,
) -> Page[EventAdminDetail]:
    """Includes drafts and cancelled events, unlike the public listing."""
    rows, total = await service.list_admin_events(pagination, status=event_status, search=search)
    return Page.build(
        [EventAdminDetail.model_validate(row) for row in rows],
        total=total,
        params=pagination,
    )


@router.post(
    "/events",
    response_model=EventAdminDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Create an event (draft)",
)
async def create_event(
    payload: EventCreate, actor: RequireAdmin, service: CatalogueServiceDep
) -> EventAdminDetail:
    """Created as a DRAFT. Publishing is a separate, deliberate action."""
    event = await service.create_event(payload, actor=actor)
    return EventAdminDetail.model_validate(await service.admin_event(event.id))


@router.get("/events/{event_id}", response_model=EventAdminDetail, summary="Event detail")
async def event_detail(
    event_id: uuid.UUID, actor: RequireAdmin, service: CatalogueServiceDep
) -> EventAdminDetail:
    return EventAdminDetail.model_validate(await service.admin_event(event_id))


@router.patch("/events/{event_id}", response_model=EventAdminDetail, summary="Update an event")
async def update_event(
    event_id: uuid.UUID,
    payload: EventUpdate,
    actor: RequireAdmin,
    service: CatalogueServiceDep,
) -> EventAdminDetail:
    await service.update_event(event_id, payload, actor=actor)
    return EventAdminDetail.model_validate(await service.admin_event(event_id))


@router.post(
    "/events/{event_id}/publish",
    response_model=EventAdminDetail,
    summary="Publish an event",
)
async def publish_event(
    event_id: uuid.UUID, actor: RequireAdmin, service: CatalogueServiceDep
) -> EventAdminDetail:
    """Refused unless the event has at least one active category with capacity."""
    await service.publish_event(event_id, actor=actor)
    return EventAdminDetail.model_validate(await service.admin_event(event_id))


@router.post(
    "/events/{event_id}/unpublish",
    response_model=EventAdminDetail,
    summary="Return an event to draft",
)
async def unpublish_event(
    event_id: uuid.UUID, actor: RequireAdmin, service: CatalogueServiceDep
) -> EventAdminDetail:
    """Stops new sales. Existing bookings are untouched."""
    await service.unpublish_event(event_id, actor=actor)
    return EventAdminDetail.model_validate(await service.admin_event(event_id))


@router.post(
    "/events/{event_id}/cancel",
    response_model=EventAdminDetail,
    summary="Cancel an event and refund its bookings",
)
async def cancel_event(
    event_id: uuid.UUID,
    payload: EventCancelRequest,
    actor: RequireAdmin,
    service: CatalogueServiceDep,
    outbox: OutboxServiceDep,
) -> EventAdminDetail:
    """Refunds are queued, not performed here.

    A sold-out event is thousands of bookings and each refund is a provider
    call; the worker processes them in batches. Event cancellation is always a
    full refund — the per-event cancellation tiers apply to *customer*
    cancellations, not to the company calling the show off.
    """
    await service.cancel_event(
        event_id,
        reason=payload.reason,
        refund_bookings=payload.refund_bookings,
        actor=actor,
        outbox=outbox,
    )
    return EventAdminDetail.model_validate(await service.admin_event(event_id))


# -------------------------------------------------------- ticket categories ---


@router.post(
    "/events/{event_id}/ticket-categories",
    response_model=TicketCategoryAdmin,
    status_code=status.HTTP_201_CREATED,
    summary="Add a ticket category",
)
async def add_ticket_category(
    event_id: uuid.UUID,
    payload: TicketCategoryCreate,
    actor: RequireAdmin,
    service: CatalogueServiceDep,
) -> TicketCategoryAdmin:
    category = await service.add_category(event_id, payload, actor=actor)
    return TicketCategoryAdmin.model_validate(category)


@router.patch(
    "/ticket-categories/{category_id}",
    response_model=TicketCategoryAdmin,
    summary="Update a ticket category",
)
async def update_ticket_category(
    category_id: uuid.UUID,
    payload: TicketCategoryUpdate,
    actor: RequireAdmin,
    service: CatalogueServiceDep,
) -> TicketCategoryAdmin:
    """Capacity may be raised freely, but never below what is sold or held."""
    category = await service.update_category(category_id, payload, actor=actor)
    return TicketCategoryAdmin.model_validate(category)


@router.delete(
    "/ticket-categories/{category_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an unsold ticket category",
)
async def delete_ticket_category(
    category_id: uuid.UUID, actor: RequireAdmin, service: CatalogueServiceDep
) -> None:
    """A category with sales is deactivated instead — deleting it would break
    the record of what customers bought."""
    await service.delete_category(category_id, actor=actor)
