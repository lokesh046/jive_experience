"""Public catalogue routes.

Unauthenticated and cached. During a ticket release this is the busiest
surface by two orders of magnitude, so every handler here is a cache read in
the common case.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query, Response

from app.core.pagination import Page
from app.dependencies import CatalogueServiceDep, Pagination
from app.models.event import EventCategory
from app.schemas.catalogue import EventAvailability, EventDetail, EventListItem

router = APIRouter(tags=["events"])


@router.get(
    "",
    response_model=Page[EventListItem],
    summary="List published events",
)
async def list_events(
    service: CatalogueServiceDep,
    pagination: Pagination,
    response: Response,
    city: Annotated[str | None, Query(description="Filter by venue city")] = None,
    category: Annotated[EventCategory | None, Query()] = None,
    starts_after: Annotated[datetime | None, Query()] = None,
    starts_before: Annotated[datetime | None, Query()] = None,
    search: Annotated[str | None, Query(max_length=120)] = None,
    featured: Annotated[bool | None, Query()] = None,
    past: Annotated[bool, Query(description="Past events instead of upcoming")] = False,
) -> Page[EventListItem]:
    """Published events only. Drafts and cancelled events are never listed."""
    items, total, from_cache = await service.public_list(
        pagination,
        city=city,
        category=category,
        starts_after=starts_after,
        starts_before=starts_before,
        search=search,
        featured=featured,
        past=past,
    )
    response.headers["X-Cache"] = "HIT" if from_cache else "MISS"
    return Page.build(
        [EventListItem.model_validate(item) for item in items],
        total=total,
        params=pagination,
    )


@router.get("/cities", response_model=list[str], summary="Cities with events")
async def list_cities(service: CatalogueServiceDep) -> list[str]:
    return list(await service.cities())


@router.get(
    "/{slug}",
    response_model=EventDetail,
    summary="Event detail by slug",
)
async def event_detail(slug: str, service: CatalogueServiceDep) -> EventDetail:
    """A draft or cancelled event returns 404, not 403 — an unannounced event
    must not be discoverable by probing slugs."""
    return EventDetail.model_validate(await service.public_detail(slug))


@router.get(
    "/{slug}/availability",
    response_model=EventAvailability,
    summary="Live ticket availability",
)
async def event_availability(slug: str, service: CatalogueServiceDep) -> EventAvailability:
    """Cached for a couple of seconds.

    The authoritative check happens inside the reservation transaction, so a
    count that is two seconds old is harmless — and this endpoint carries far
    more traffic than the sales do.
    """
    return await service.availability(slug)
