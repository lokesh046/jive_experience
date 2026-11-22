"""Venue and event rules.

Caching policy: reads populate the cache, and every write invalidates the
affected entries **after** its transaction commits. Invalidating before the
commit would let a concurrent reader repopulate the cache from the pre-change
row and leave it stale until the TTL expires.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import BusinessRuleError, ConflictError, NotFoundError
from app.core.pagination import PageParams
from app.models.event import (
    PUBLIC_EVENT_STATUSES,
    Event,
    EventCategory,
    EventPerformer,
    EventStatus,
    TicketCategory,
)
from app.models.fulfilment import TicketStatus
from app.models.user import User
from app.models.venue import Venue
from app.repositories.catalogue import (
    EventRepository,
    TicketCategoryRepository,
    VenueRepository,
)
from app.repositories.commerce import InventoryRepository
from app.repositories.fulfilment import TicketRepository
from app.schemas.catalogue import (
    AvailabilityItem,
    EventAvailability,
    EventCreate,
    EventUpdate,
    LineupReplace,
    TicketCategoryCreate,
    TicketCategoryUpdate,
    VenueCreate,
    VenueUpdate,
    slugify,
)
from app.services.audit import AuditService
from app.services.cache import (
    AVAILABILITY_TTL,
    EVENT_DETAIL_TTL,
    EVENT_LIST_TTL,
    VENUE_CITIES_TTL,
    CatalogueCache,
)
from app.services.outbox import TOPIC_EVENT_CANCELLED, OutboxService

logger = structlog.get_logger(__name__)


def list_fingerprint(**filters: Any) -> str:
    """A stable cache key for one combination of filters and page.

    Hashed so the key length does not grow with the filter set, and sorted so
    the same filters always produce the same key whatever order they arrive
    in.
    """
    payload = json.dumps(filters, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:32]


class CatalogueService:
    def __init__(
        self,
        session: AsyncSession,
        cache: CatalogueCache,
    ) -> None:
        self.session = session
        self.cache = cache
        self.venues = VenueRepository(session)
        self.events = EventRepository(session)
        self.categories = TicketCategoryRepository(session)
        self.inventory = InventoryRepository(session)
        self.tickets = TicketRepository(session)
        self.audit = AuditService(session)

    # ------------------------------------------------------------ venues ---

    async def create_venue(self, payload: VenueCreate, *, actor: User) -> Venue:
        if await self.venues.by_name_and_city(payload.name, payload.city):
            raise ConflictError(
                "A venue with that name already exists in this city.",
                code="VENUE_EXISTS",
            )

        venue = Venue(**payload.model_dump())
        self.venues.add(venue)
        await self.session.flush()
        await self.audit.record(
            "venue.created",
            entity_type="venue",
            entity_id=venue.id,
            actor=actor,
            after={"name": venue.name, "city": venue.city},
        )
        await self.session.commit()
        await self.cache.invalidate_cities()
        return venue

    async def update_venue(
        self, venue_id: uuid.UUID, payload: VenueUpdate, *, actor: User
    ) -> Venue:
        venue = await self.venues.get_or_fail(venue_id)
        before = {"name": venue.name, "city": venue.city}

        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(venue, field, value)

        await self.audit.record(
            "venue.updated",
            entity_type="venue",
            entity_id=venue.id,
            actor=actor,
            before=before,
            after={"name": venue.name, "city": venue.city},
        )
        await self.session.commit()

        # A venue rename or move changes every event that shows it — the
        # cards in the listing and the venue block on each detail page. The
        # detail entries have their own keys, so clearing the lists alone
        # would leave the old address on screen until the TTL expired.
        await self.cache.invalidate_lists()
        await self.cache.invalidate_cities()
        await self.cache.invalidate_details(list(await self.events.slugs_at_venue(venue_id)))
        return venue

    async def list_venues(self, params: PageParams) -> tuple[Sequence[Venue], int]:
        return await self.venues.paginate(params, order_by=[Venue.name.asc()])

    async def cities(self) -> Sequence[str]:
        cached = await self.cache.get_json(self.cache.cities_key())
        if cached is not None:
            return list(cached)
        cities = await self.venues.cities()
        await self.cache.set_json(self.cache.cities_key(), list(cities), ttl=VENUE_CITIES_TTL)
        return cities

    # ------------------------------------------------------- public reads ---

    async def public_list(
        self,
        params: PageParams,
        *,
        city: str | None = None,
        category: EventCategory | None = None,
        starts_after: datetime | None = None,
        starts_before: datetime | None = None,
        search: str | None = None,
        featured: bool | None = None,
        past: bool = False,
    ) -> tuple[list[dict[str, Any]], int, bool]:
        """A page of public events, from cache when possible.

        Returns `(items, total, from_cache)`. The caller serialises; the
        cached value is already the serialised form so a hit costs no ORM work
        at all.
        """
        now = datetime.now(UTC)

        # "Upcoming" and "past" are relative to now, but putting a raw
        # timestamp in the cache key would make every request a unique key and
        # the cache would never hit. The derived bound is bucketed to the TTL
        # instead: the key changes once per TTL window, so an entry is never
        # more stale than it would have been anyway.
        explicit_after, explicit_before = starts_after, starts_before
        if past:
            starts_before = explicit_before or now
        else:
            starts_after = explicit_after or now
        now_bucket = int(now.timestamp()) // EVENT_LIST_TTL

        key = self.cache.list_key(
            list_fingerprint(
                page=params.page,
                size=params.size,
                city=city,
                category=category.value if category else None,
                starts_after=explicit_after,
                starts_before=explicit_before,
                now_bucket=now_bucket,
                search=search,
                featured=featured,
                past=past,
            )
        )
        cached = await self.cache.get_json(key)
        if cached is not None:
            return cached["items"], int(cached["total"]), True

        rows, total = await self.events.list_public(
            params,
            city=city,
            category=category,
            starts_after=starts_after,
            starts_before=starts_before,
            search=search,
            featured=featured,
            upcoming_first=not past,
        )
        items = [self.to_list_item(event) for event in rows]
        await self.cache.set_json(key, {"items": items, "total": total}, ttl=EVENT_LIST_TTL)
        return items, total, False

    async def public_detail(self, slug: str) -> dict[str, Any]:
        key = self.cache.detail_key(slug)
        cached = await self.cache.get_json(key)
        if cached is not None:
            return dict(cached)

        event = await self.events.public_by_slug(slug)
        if event is None:
            # Draft and cancelled events are indistinguishable from events
            # that never existed — a 404, not a 403, so an unannounced event
            # cannot be discovered by probing slugs.
            raise NotFoundError("Event not found.", code="EVENT_NOT_FOUND")

        detail = self.to_detail(event)
        await self.cache.set_json(key, detail, ttl=EVENT_DETAIL_TTL)
        return detail

    async def availability(self, slug: str) -> EventAvailability:
        """Live-ish availability for the booking page.

        Cached for a couple of seconds. During a drop this endpoint carries
        far more traffic than the sales themselves, and showing "47 left"
        instead of "46 left" for two seconds changes nothing: the real check
        happens inside the reservation transaction.
        """
        event = await self.events.public_by_slug(slug)
        if event is None:
            raise NotFoundError("Event not found.", code="EVENT_NOT_FOUND")

        key = self.cache.availability_key(str(event.id))
        cached = await self.cache.get_json(key)
        if cached is not None:
            return EventAvailability.model_validate(cached)

        remaining = await self.inventory.availability(event.id)
        categories = [
            AvailabilityItem(
                ticket_category_id=category.id,
                name=category.name,
                price_paise=category.price_paise,
                available=max(remaining.get(category.id, 0), 0),
                is_sold_out=remaining.get(category.id, 0) <= 0,
            )
            for category in sorted(event.ticket_categories, key=lambda c: c.sort_order)
            if category.is_active
        ]
        payload = EventAvailability(
            event_id=event.id,
            checked_at=datetime.now(UTC),
            total_available=sum(item.available for item in categories),
            categories=categories,
        )
        await self.cache.set_json(key, payload.model_dump(), ttl=AVAILABILITY_TTL)
        return payload

    # ------------------------------------------------------ admin writes ---

    async def create_event(self, payload: EventCreate, *, actor: User) -> Event:
        await self.venues.get_or_fail(payload.venue_id)

        slug = payload.slug or slugify(payload.title)
        if await self.events.slug_taken(slug):
            raise ConflictError("That event URL is already in use.", code="EVENT_SLUG_TAKEN")

        data = payload.model_dump(exclude={"slug"})
        event = Event(**data, slug=slug, status=EventStatus.DRAFT, created_by_id=actor.id)
        self.events.add(event)
        await self.session.flush()

        await self.audit.record(
            "event.created",
            entity_type="event",
            entity_id=event.id,
            actor=actor,
            after={"slug": slug, "title": event.title},
        )
        await self.session.commit()
        # A draft is not publicly visible, so no public cache entry changes.
        return event

    async def update_event(
        self, event_id: uuid.UUID, payload: EventUpdate, *, actor: User
    ) -> Event:
        event = await self.events.with_categories(event_id)
        if event is None:
            raise NotFoundError("Event not found.", code="EVENT_NOT_FOUND")

        previous_slug = event.slug
        updates = payload.model_dump(exclude_unset=True)

        if "venue_id" in updates and updates["venue_id"] is not None:
            await self.venues.get_or_fail(updates["venue_id"])
        if updates.get("slug") and await self.events.slug_taken(
            updates["slug"], excluding=event.id
        ):
            raise ConflictError("That event URL is already in use.", code="EVENT_SLUG_TAKEN")

        before = {"title": event.title, "slug": event.slug, "status": event.status.value}
        for field, value in updates.items():
            setattr(event, field, value)

        await self.audit.record(
            "event.updated",
            entity_type="event",
            entity_id=event.id,
            actor=actor,
            before=before,
            after={"title": event.title, "slug": event.slug},
        )
        await self.session.commit()
        await self.cache.invalidate_event(slug=previous_slug, event_id=str(event.id))
        if event.slug != previous_slug:
            await self.cache.invalidate_event(slug=event.slug, event_id=str(event.id))
        return event

    async def publish_event(self, event_id: uuid.UUID, *, actor: User) -> Event:
        """Make an event visible and sellable.

        Refused without at least one active ticket category: a published event
        nobody can buy into is a support call, not a sale.
        """
        event = await self.events.with_categories(event_id)
        if event is None:
            raise NotFoundError("Event not found.", code="EVENT_NOT_FOUND")
        if event.status is EventStatus.CANCELLED:
            raise BusinessRuleError(
                "A cancelled event cannot be published.", code="EVENT_CANCELLED"
            )

        sellable = [c for c in event.ticket_categories if c.is_active and c.capacity > 0]
        if not sellable:
            raise BusinessRuleError(
                "Add at least one active ticket category with capacity before publishing.",
                code="EVENT_NOT_SELLABLE",
            )

        event.status = EventStatus.PUBLISHED
        event.published_at = event.published_at or datetime.now(UTC)

        await self.audit.record(
            "event.published",
            entity_type="event",
            entity_id=event.id,
            actor=actor,
            after={"slug": event.slug, "categories": len(sellable)},
        )
        await self.session.commit()
        await self.cache.invalidate_event(slug=event.slug, event_id=str(event.id))
        logger.info("event_published", event_id=str(event.id), slug=event.slug)
        return event

    async def unpublish_event(self, event_id: uuid.UUID, *, actor: User) -> Event:
        """Return a published event to draft.

        Existing bookings are untouched — they were paid for. This only stops
        new sales.
        """
        event = await self.events.with_categories(event_id)
        if event is None:
            raise NotFoundError("Event not found.", code="EVENT_NOT_FOUND")
        if event.status not in PUBLIC_EVENT_STATUSES:
            raise BusinessRuleError(
                "Only a published event can be unpublished.", code="EVENT_NOT_PUBLISHED"
            )

        event.status = EventStatus.DRAFT
        await self.audit.record(
            "event.unpublished",
            entity_type="event",
            entity_id=event.id,
            actor=actor,
            before={"status": EventStatus.PUBLISHED.value},
        )
        await self.session.commit()
        await self.cache.invalidate_event(slug=event.slug, event_id=str(event.id))
        return event

    async def cancel_event(
        self,
        event_id: uuid.UUID,
        *,
        reason: str,
        refund_bookings: bool,
        actor: User,
        outbox: OutboxService,
    ) -> Event:
        """Cancel an event and queue the refunds.

        The refunds are queued rather than performed here: a sold-out event is
        thousands of bookings and each refund is a provider call. The worker
        works through them in batches, and the operator gets an immediate
        answer.
        """
        event = await self.events.with_categories(event_id)
        if event is None:
            raise NotFoundError("Event not found.", code="EVENT_NOT_FOUND")
        if event.status is EventStatus.CANCELLED:
            raise BusinessRuleError(
                "This event is already cancelled.", code="EVENT_ALREADY_CANCELLED"
            )

        now = datetime.now(UTC)
        event.status = EventStatus.CANCELLED
        event.cancelled_at = now
        event.cancellation_reason = reason

        # Void every unused ticket here, in the same transaction that cancels
        # the event — not in the refund job. Refunds are batched and may be
        # declined entirely (`refund_bookings=False`), and a ticket that
        # still reads ISSUED is one the gate will accept. Money is settled
        # asynchronously; admission is not.
        voided = await self.tickets.invalidate_for_event(
            event.id, status=TicketStatus.CANCELLED, now=now
        )

        if refund_bookings:
            await outbox.enqueue(
                topic=TOPIC_EVENT_CANCELLED,
                payload={"event_id": str(event.id)},
                dedup_key=f"event.cancelled:{event.id}",
            )

        await self.audit.record(
            "event.cancelled",
            entity_type="event",
            entity_id=event.id,
            actor=actor,
            after={
                "reason": reason,
                "refund_bookings": refund_bookings,
                "tickets_voided": voided,
            },
        )
        await self.session.commit()
        await self.cache.invalidate_event(slug=event.slug, event_id=str(event.id))
        logger.info(
            "event_cancelled",
            event_id=str(event.id),
            refund_bookings=refund_bookings,
            tickets_voided=voided,
        )
        return event

    async def list_admin_events(
        self, params: PageParams, *, status: str | None = None, search: str | None = None
    ) -> tuple[Sequence[Event], int]:
        return await self.events.list_admin(params, status=status, search=search)

    async def admin_event(self, event_id: uuid.UUID) -> Event:
        event = await self.events.with_categories(event_id)
        if event is None:
            raise NotFoundError("Event not found.", code="EVENT_NOT_FOUND")
        return event

    # -------------------------------------------------- ticket categories ---

    async def add_category(
        self, event_id: uuid.UUID, payload: TicketCategoryCreate, *, actor: User
    ) -> TicketCategory:
        event = await self.events.get_or_fail(event_id)
        if await self.categories.name_taken(event_id, payload.name):
            raise ConflictError(
                "That ticket category name already exists for this event.",
                code="CATEGORY_NAME_TAKEN",
            )

        category = TicketCategory(event_id=event_id, **payload.model_dump())
        self.categories.add(category)
        await self.session.flush()

        await self.audit.record(
            "ticket_category.created",
            entity_type="ticket_category",
            entity_id=category.id,
            actor=actor,
            after={
                "event_id": str(event_id),
                "name": category.name,
                "price_paise": category.price_paise,
                "capacity": category.capacity,
            },
        )
        await self.session.commit()
        await self.cache.invalidate_event(slug=event.slug, event_id=str(event_id))
        return category

    async def update_category(
        self,
        category_id: uuid.UUID,
        payload: TicketCategoryUpdate,
        *,
        actor: User,
    ) -> TicketCategory:
        """Change a price band.

        Capacity may be raised freely but never reduced below what is already
        sold or held — that would make the not-oversold constraint false and
        the write would be rejected by the database anyway.
        """
        category = await self.categories.get_or_fail(category_id)
        updates = payload.model_dump(exclude_unset=True)

        if updates.get("name") and await self.categories.name_taken(
            category.event_id, updates["name"], excluding=category.id
        ):
            raise ConflictError(
                "That ticket category name already exists for this event.",
                code="CATEGORY_NAME_TAKEN",
            )

        if "capacity" in updates and updates["capacity"] is not None:
            committed = category.sold_count + category.reserved_count
            if updates["capacity"] < committed:
                raise BusinessRuleError(
                    f"Capacity cannot be below the {committed} tickets already sold or held.",
                    code="CAPACITY_BELOW_COMMITTED",
                    details={"committed": committed},
                )

        before = {"price_paise": category.price_paise, "capacity": category.capacity}
        for field, value in updates.items():
            setattr(category, field, value)

        await self.audit.record(
            "ticket_category.updated",
            entity_type="ticket_category",
            entity_id=category.id,
            actor=actor,
            before=before,
            after={"price_paise": category.price_paise, "capacity": category.capacity},
        )
        await self.session.commit()

        event = await self.events.get(category.event_id)
        await self.cache.invalidate_event(
            slug=event.slug if event else None, event_id=str(category.event_id)
        )
        return category

    async def delete_category(self, category_id: uuid.UUID, *, actor: User) -> None:
        """Remove a category that has never sold anything.

        A category with sales is deactivated instead — deleting it would break
        the foreign key from booking items, and with it the record of what a
        customer actually bought.
        """
        category = await self.categories.get_or_fail(category_id)
        if category.sold_count or category.reserved_count:
            raise BusinessRuleError(
                "This category has tickets sold or held; deactivate it instead.",
                code="CATEGORY_IN_USE",
            )

        event_id = category.event_id
        await self.categories.delete(category)
        await self.audit.record(
            "ticket_category.deleted",
            entity_type="ticket_category",
            entity_id=category_id,
            actor=actor,
            before={"name": category.name, "event_id": str(event_id)},
        )
        await self.session.commit()

        event = await self.events.get(event_id)
        await self.cache.invalidate_event(
            slug=event.slug if event else None, event_id=str(event_id)
        )

    # ------------------------------------------------------------ lineup ---

    async def replace_lineup(
        self, event_id: uuid.UUID, payload: LineupReplace, *, actor: User
    ) -> Event:
        """Set the whole lineup, in running order.

        Replacing the list in one transaction (rather than add/edit/remove
        calls) keeps the order and the content consistent however the admin
        rearranged it, and a failed save changes nothing.
        """
        event = await self.events.get_or_fail(event_id)
        before = len(event.performers)
        event.performers = [
            EventPerformer(
                name=p.name,
                role=p.role,
                photo_url=p.photo_url,
                performs_at=p.performs_at,
                sort_order=position,
            )
            for position, p in enumerate(payload.performers)
        ]
        await self.audit.record(
            "event.lineup_replaced",
            entity_type="event",
            entity_id=event.id,
            actor=actor,
            before={"performers": before},
            after={"performers": len(payload.performers)},
        )
        await self.session.commit()
        await self.cache.invalidate_event(slug=event.slug, event_id=str(event_id))
        return await self.admin_event(event_id)

    # ------------------------------------------------------ serialisation ---

    @staticmethod
    def _starting_price(event: Event) -> int | None:
        prices = [c.price_paise for c in event.ticket_categories if c.is_active]
        return min(prices) if prices else None

    @staticmethod
    def _is_sold_out(event: Event) -> bool:
        active = [c for c in event.ticket_categories if c.is_active]
        if not active:
            return False
        return all(c.available <= 0 for c in active)

    @classmethod
    def to_list_item(cls, event: Event) -> dict[str, Any]:
        return {
            "id": str(event.id),
            "slug": event.slug,
            "title": event.title,
            "subtitle": event.subtitle,
            "category": event.category.value,
            "status": event.status.value,
            "starts_at": event.starts_at.isoformat(),
            "timezone": event.timezone,
            "venue_name": event.venue.name,
            "city": event.venue.city,
            "thumbnail_image_url": event.thumbnail_image_url,
            "banner_image_url": event.banner_image_url,
            "starting_price_paise": cls._starting_price(event),
            "is_featured": event.is_featured,
            "is_sold_out": cls._is_sold_out(event),
        }

    @classmethod
    def to_detail(cls, event: Event) -> dict[str, Any]:
        now = datetime.now(UTC)
        # Once an event has started it is "past": the same cut-off the public list uses, and
        # the point at which the booking service stops selling.
        is_past = event.starts_at <= now
        on_sale = (
            event.status is EventStatus.PUBLISHED
            and not is_past
            and (event.sale_starts_at is None or event.sale_starts_at <= now)
            and (event.sale_ends_at is None or event.sale_ends_at >= now)
        )
        return {
            "id": str(event.id),
            "slug": event.slug,
            "title": event.title,
            "subtitle": event.subtitle,
            "description": event.description,
            "category": event.category.value,
            "status": event.status.value,
            "starts_at": event.starts_at.isoformat(),
            "ends_at": event.ends_at.isoformat() if event.ends_at else None,
            "timezone": event.timezone,
            "sale_starts_at": event.sale_starts_at.isoformat() if event.sale_starts_at else None,
            "sale_ends_at": event.sale_ends_at.isoformat() if event.sale_ends_at else None,
            "on_sale": on_sale,
            "is_past": is_past,
            "venue": {
                "id": str(event.venue.id),
                "name": event.venue.name,
                "address_line1": event.venue.address_line1,
                "address_line2": event.venue.address_line2,
                "city": event.venue.city,
                "state": event.venue.state,
                "postal_code": event.venue.postal_code,
                "country_code": event.venue.country_code,
                "latitude": float(event.venue.latitude) if event.venue.latitude else None,
                "longitude": float(event.venue.longitude) if event.venue.longitude else None,
                "map_url": event.venue.map_url,
                "directions": event.venue.directions,
                "description": event.venue.description,
                "image_urls": event.venue.image_urls or [],
                "benefits": event.venue.benefits or [],
            },
            "banner_image_url": event.banner_image_url,
            "thumbnail_image_url": event.thumbnail_image_url,
            "gallery_image_urls": event.gallery_image_urls or [],
            "ticket_categories": [
                {
                    "id": str(c.id),
                    "name": c.name,
                    "description": c.description,
                    "price_paise": c.price_paise,
                    "currency": c.currency,
                    "available": max(c.available, 0),
                    "min_per_booking": c.min_per_booking,
                    "max_per_booking": c.max_per_booking,
                    "is_sold_out": c.available <= 0,
                }
                for c in sorted(event.ticket_categories, key=lambda c: c.sort_order)
                if c.is_active
            ],
            "lineup": [
                {
                    "name": p.name,
                    "role": p.role,
                    "photo_url": p.photo_url,
                    "performs_at": p.performs_at.isoformat() if p.performs_at else None,
                }
                for p in event.performers
            ],
            "max_tickets_per_customer": event.max_tickets_per_customer,
            "requires_attendee_name": event.requires_attendee_name,
            "cancellation_policy": event.cancellation_policy,
            "terms_and_conditions": event.terms_and_conditions,
            "location_url": event.location_url,
            "is_sold_out": cls._is_sold_out(event),
        }
