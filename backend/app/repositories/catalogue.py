"""Venue, event and ticket-category queries."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.orm import joinedload, selectinload

from app.core.pagination import PageParams
from app.models.event import PUBLIC_EVENT_STATUSES, Event, EventCategory, TicketCategory
from app.models.venue import Venue
from app.repositories.base import BaseRepository


class VenueRepository(BaseRepository[Venue]):
    model = Venue

    async def by_name_and_city(self, name: str, city: str) -> Venue | None:
        return await self.find_one(Venue.name == name, Venue.city == city)

    async def cities(self) -> Sequence[str]:
        """Distinct cities, for the public filter dropdown."""
        result = await self.session.execute(select(Venue.city).distinct().order_by(Venue.city))
        return result.scalars().all()


class EventRepository(BaseRepository[Event]):
    model = Event

    def _public_base(self) -> Select[Event]:
        """Published (or sold-out) events, with venue and categories loaded.

        `joinedload` on the venue and `selectinload` on the categories: a list
        page needs both, and lazy loading would issue a query per row.
        """
        return (
            select(Event)
            .where(Event.status.in_(PUBLIC_EVENT_STATUSES))
            .options(
                joinedload(Event.venue),
                selectinload(Event.ticket_categories),
            )
        )

    @staticmethod
    def _apply_filters[S: Select[Any]](
        statement: S,
        *,
        city: str | None,
        category: EventCategory | None,
        starts_after: datetime | None,
        starts_before: datetime | None,
        search: str | None,
        featured: bool | None,
    ) -> S:
        """Shared WHERE clauses, applied to both the page and the count.

        Generic over the select so the row query and the `count()` query can
        never drift apart — a filter added in one is automatically in both.
        """
        if city:
            statement = statement.join(Venue, Event.venue_id == Venue.id).where(
                func.lower(Venue.city) == city.lower()
            )
        if category is not None:
            statement = statement.where(Event.category == category)
        if starts_after is not None:
            statement = statement.where(Event.starts_at >= starts_after)
        if starts_before is not None:
            statement = statement.where(Event.starts_at <= starts_before)
        if search:
            statement = statement.where(Event.title.ilike(f"%{search}%"))
        if featured is not None:
            statement = statement.where(Event.is_featured.is_(featured))
        return statement

    async def list_public(
        self,
        params: PageParams,
        *,
        city: str | None = None,
        category: EventCategory | None = None,
        starts_after: datetime | None = None,
        starts_before: datetime | None = None,
        search: str | None = None,
        featured: bool | None = None,
        upcoming_first: bool = True,
    ) -> tuple[Sequence[Event], int]:
        """One page of public events plus the total matching count."""
        statement = self._apply_filters(
            self._public_base(),
            city=city,
            category=category,
            starts_after=starts_after,
            starts_before=starts_before,
            search=search,
            featured=featured,
        )
        order = Event.starts_at.asc() if upcoming_first else Event.starts_at.desc()
        statement = statement.order_by(order, Event.id).offset(params.offset).limit(params.limit)

        rows = (await self.session.execute(statement)).scalars().unique().all()

        count_statement = self._apply_filters(
            select(func.count()).select_from(Event).where(Event.status.in_(PUBLIC_EVENT_STATUSES)),
            city=city,
            category=category,
            starts_after=starts_after,
            starts_before=starts_before,
            search=search,
            featured=featured,
        )
        total = int(await self.session.scalar(count_statement) or 0)
        return rows, total

    async def public_by_slug(self, slug: str) -> Event | None:
        """A single published event, for the detail page."""
        statement = self._public_base().where(Event.slug == slug)
        return (await self.session.execute(statement)).scalars().unique().one_or_none()

    async def by_slug(self, slug: str) -> Event | None:
        """Any event regardless of status — administrators only."""
        statement = (
            select(Event)
            .where(Event.slug == slug)
            .options(joinedload(Event.venue), selectinload(Event.ticket_categories))
        )
        return (await self.session.execute(statement)).scalars().unique().one_or_none()

    async def with_categories(self, event_id: uuid.UUID) -> Event | None:
        statement = (
            select(Event)
            .where(Event.id == event_id)
            .options(joinedload(Event.venue), selectinload(Event.ticket_categories))
        )
        return (await self.session.execute(statement)).scalars().unique().one_or_none()

    async def slugs_at_venue(self, venue_id: uuid.UUID) -> Sequence[str]:
        """Slugs of every event at a venue, for cache invalidation."""
        result = await self.session.execute(select(Event.slug).where(Event.venue_id == venue_id))
        return result.scalars().all()

    async def for_scanning(self, since: datetime) -> Sequence[Event]:
        """Live events from `since` onward, for an administrator's scanner picker."""
        result = await self.session.execute(
            select(Event)
            .where(
                Event.status.in_(PUBLIC_EVENT_STATUSES),
                Event.starts_at >= since,
            )
            .order_by(Event.starts_at.asc())
            .limit(100)
        )
        return result.scalars().all()

    async def public_slugs(self) -> Sequence[str]:
        """Slugs of every event a customer can see, for cache invalidation."""
        result = await self.session.execute(
            select(Event.slug).where(Event.status.in_(PUBLIC_EVENT_STATUSES))
        )
        return result.scalars().all()

    async def slug_taken(self, slug: str, *, excluding: uuid.UUID | None = None) -> bool:
        conditions = [Event.slug == slug]
        if excluding is not None:
            conditions.append(Event.id != excluding)
        return await self.exists(*conditions)

    async def list_admin(
        self,
        params: PageParams,
        *,
        status: str | None = None,
        search: str | None = None,
    ) -> tuple[Sequence[Event], int]:
        statement = select(Event).options(
            joinedload(Event.venue), selectinload(Event.ticket_categories)
        )
        count_statement = select(func.count()).select_from(Event)
        if status:
            statement = statement.where(Event.status == status)
            count_statement = count_statement.where(Event.status == status)
        if search:
            statement = statement.where(Event.title.ilike(f"%{search}%"))
            count_statement = count_statement.where(Event.title.ilike(f"%{search}%"))

        statement = (
            statement.order_by(Event.starts_at.desc(), Event.id)
            .offset(params.offset)
            .limit(params.limit)
        )
        rows = (await self.session.execute(statement)).scalars().unique().all()
        total = int(await self.session.scalar(count_statement) or 0)
        return rows, total


class TicketCategoryRepository(BaseRepository[TicketCategory]):
    model = TicketCategory

    async def for_event(self, event_id: uuid.UUID) -> Sequence[TicketCategory]:
        return await self.list(
            TicketCategory.event_id == event_id,
            order_by=[TicketCategory.sort_order.asc(), TicketCategory.name.asc()],
        )

    async def active_for_event(self, event_id: uuid.UUID) -> Sequence[TicketCategory]:
        return await self.list(
            TicketCategory.event_id == event_id,
            TicketCategory.is_active.is_(True),
            order_by=[TicketCategory.sort_order.asc()],
        )

    async def name_taken(
        self, event_id: uuid.UUID, name: str, *, excluding: uuid.UUID | None = None
    ) -> bool:
        conditions = [TicketCategory.event_id == event_id, TicketCategory.name == name]
        if excluding is not None:
            conditions.append(TicketCategory.id != excluding)
        return await self.exists(*conditions)

    async def remaining_for_event(self, event_id: uuid.UUID) -> int:
        """Total tickets still sellable across every active category."""
        statement = select(
            func.coalesce(
                func.sum(
                    TicketCategory.capacity
                    - TicketCategory.sold_count
                    - TicketCategory.reserved_count
                ),
                0,
            )
        ).where(TicketCategory.event_id == event_id, TicketCategory.is_active.is_(True))
        return int(await self.session.scalar(statement) or 0)
