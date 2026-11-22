"""The waitlist: joining, leaving, and telling people when tickets come back."""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import BusinessRuleError, ConflictError, NotFoundError
from app.core.pagination import PageParams
from app.models.event import Event, EventStatus
from app.models.waitlist import WaitlistEntry, WaitlistStatus
from app.repositories.catalogue import EventRepository, TicketCategoryRepository
from app.repositories.waitlist import WaitlistRepository
from app.schemas.waitlist import WaitlistJoin, WaitlistRowOut
from app.services.outbox import TOPIC_WAITLIST_AVAILABLE, OutboxService

logger = structlog.get_logger(__name__)

# More people are told than there are tickets, because not everyone will buy.
NOTIFY_BUFFER = 2
# Someone told this recently may still be about to buy, so they count against the tickets.
OUTSTANDING_FOR = timedelta(hours=24)


class WaitlistService:
    def __init__(self, session: AsyncSession, outbox: OutboxService) -> None:
        self.session = session
        self.outbox = outbox
        self.entries = WaitlistRepository(session)
        self.events = EventRepository(session)
        self.categories = TicketCategoryRepository(session)

    # ------------------------------------------------------------ public ---

    async def join(self, slug: str, payload: WaitlistJoin) -> None:
        if payload.website:
            logger.info("waitlist_honeypot_tripped")
            return
        event = await self.events.public_by_slug(slug)
        if event is None:
            raise NotFoundError("Event not found.", code="EVENT_NOT_FOUND")
        if event.status is not EventStatus.PUBLISHED and event.status is not EventStatus.SOLD_OUT:
            raise NotFoundError("Event not found.", code="EVENT_NOT_FOUND")
        if event.starts_at <= datetime.now(UTC):
            raise BusinessRuleError("This event has already started.", code="EVENT_STARTED")

        active = [c for c in event.ticket_categories if c.is_active]
        wanted = payload.ticket_category_id
        if wanted is not None:
            category = next((c for c in active if c.id == wanted), None)
            if category is None:
                raise NotFoundError("Ticket type not found.", code="CATEGORY_NOT_FOUND")
            if category.available >= payload.quantity:
                raise ConflictError(
                    "Tickets are available right now. You can book them.",
                    code="TICKETS_AVAILABLE",
                )
        elif any(c.available >= payload.quantity for c in active):
            raise ConflictError(
                "Tickets are available right now. You can book them.", code="TICKETS_AVAILABLE"
            )

        email = str(payload.email).lower()
        entry = await self.entries.for_person(event.id, email)
        if entry is None:
            entry = WaitlistEntry(
                event_id=event.id,
                email=email,
                leave_token=secrets.token_urlsafe(32),
                quantity=payload.quantity,
                ticket_category_id=wanted,
            )
            self.entries.add(entry)
        else:
            entry.quantity = payload.quantity
            entry.ticket_category_id = wanted
            entry.status = WaitlistStatus.WAITING
            entry.notified_at = None
        await self.session.commit()

    async def leave(self, token: str) -> None:
        entry = await self.entries.by_token(token)
        if entry is not None and entry.status is not WaitlistStatus.LEFT:
            entry.status = WaitlistStatus.LEFT
            await self.session.commit()

    # ------------------------------------------------------------ worker ---

    async def notify_available(self) -> int:
        """Tell waiting people that tickets are back, oldest first. Returns how many were told.

        Run by the worker. For each event with people waiting, work out how many tickets are
        free (per type, and in total for "any type"), then tell people in the order they
        joined while their request fits. An entry is only told once; if the tickets go again
        they can rejoin.
        """
        told = 0
        for event_id in await self.entries.events_with_waiting():
            event = await self.events.get(event_id)
            if event is None or not self._sellable(event):
                continue
            free = {
                c.id: max(c.available, 0) * NOTIFY_BUFFER
                for c in event.ticket_categories
                if c.is_active
            }
            total_budget = sum(free.values())
            # Take off the people already told: without this, every check would tell the
            # next few people about the same tickets until the whole list had been emailed.
            since = datetime.now(UTC) - OUTSTANDING_FOR
            for told_already in await self.entries.recently_notified(event_id, since):
                if told_already.ticket_category_id is not None:
                    if told_already.ticket_category_id in free:
                        free[told_already.ticket_category_id] -= told_already.quantity
                else:
                    self._take_from_any(free, told_already.quantity)
                total_budget -= told_already.quantity
            if total_budget <= 0:
                continue
            for entry in await self.entries.waiting_in_order(event_id):
                if entry.ticket_category_id is not None:
                    if free.get(entry.ticket_category_id, 0) < entry.quantity:
                        continue
                    free[entry.ticket_category_id] -= entry.quantity
                    total_budget -= entry.quantity
                else:
                    if total_budget < entry.quantity:
                        continue
                    total_budget -= entry.quantity
                    self._take_from_any(free, entry.quantity)
                entry.status = WaitlistStatus.NOTIFIED
                entry.notified_at = datetime.now(UTC)
                await self.outbox.enqueue(
                    topic=TOPIC_WAITLIST_AVAILABLE,
                    payload={"entry_id": str(entry.id)},
                    dedup_key=f"waitlist.available:{entry.id}:{entry.notified_at.isoformat()}",
                )
                told += 1
        if told:
            await self.session.commit()
        return told

    @staticmethod
    def _sellable(event: Event) -> bool:
        return event.status in (
            EventStatus.PUBLISHED,
            EventStatus.SOLD_OUT,
        ) and event.starts_at > datetime.now(UTC)

    @staticmethod
    def _take_from_any(free: dict[uuid.UUID, int], quantity: int) -> None:
        for category_id in sorted(free, key=lambda k: -free[k]):
            take = min(free[category_id], quantity)
            free[category_id] -= take
            quantity -= take
            if quantity <= 0:
                return

    # ------------------------------------------------------------- admin ---

    async def list_for_event(
        self, event_id: uuid.UUID, params: PageParams
    ) -> tuple[list[WaitlistRowOut], int, dict[str, int]]:
        await self.events.get_or_fail(event_id)
        rows, total = await self.entries.admin_page(event_id, params)
        return (
            [
                WaitlistRowOut(
                    email=r[0],
                    quantity=r[1],
                    ticket_type=r[2],
                    status=r[3],
                    created_at=r[4],
                    notified_at=r[5],
                )
                for r in rows
            ],
            total,
            await self.entries.counts(event_id),
        )
