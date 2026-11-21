"""Ticket inventory.

The correctness rules, in order of importance:

1. **PostgreSQL decides.** Redis caches availability for display; it never
   grants a ticket. A cache outage must not be able to oversell an event.
2. **Short transactions.** A hold takes one conditional UPDATE and commits.
   No payment-provider call, no email, no external I/O ever happens while an
   inventory row is locked — a 500 ms gateway call inside the lock would cap
   throughput at two sales per second.
3. **Release is idempotent.** Every release moves a reservation out of HELD
   first and only adjusts the counter if that transition actually happened,
   so a sweeper that runs twice returns the stock once.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import BusinessRuleError, ConflictError, NotFoundError
from app.models.commerce import ReservationStatus, TicketReservation
from app.models.event import Event, EventStatus, TicketCategory
from app.repositories.catalogue import TicketCategoryRepository
from app.repositories.commerce import (
    BookingRepository,
    InventoryRepository,
    ReservationRepository,
)

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class RequestedItem:
    ticket_category_id: uuid.UUID
    quantity: int


@dataclass(frozen=True, slots=True)
class HeldItem:
    reservation_id: uuid.UUID
    ticket_category: TicketCategory
    quantity: int
    unit_price_paise: int

    @property
    def line_total_paise(self) -> int:
        return self.unit_price_paise * self.quantity


class InventoryService:
    def __init__(self, session: AsyncSession, hold_seconds: int) -> None:
        self.session = session
        self.hold_seconds = hold_seconds
        self.inventory = InventoryRepository(session)
        self.reservations = ReservationRepository(session)
        self.categories = TicketCategoryRepository(session)
        self.bookings = BookingRepository(session)

    # ------------------------------------------------------------- lock ---

    async def lock_customer_event(self, user_id: uuid.UUID, event_id: uuid.UUID) -> None:
        """Serialise one customer's attempts on one event.

        A transaction-scoped advisory lock, released at commit. Narrow by
        design: two *different* customers never contend, so a ticket drop —
        where every buyer is a different person — sees no added
        serialisation.

        Re-entrant within a transaction, so taking it again inside `hold()`
        is free. The booking service takes it first so that its idempotency
        re-check happens inside the same critical section.
        """
        await self.session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:a), hashtext(:b))"),
            {"a": str(user_id), "b": str(event_id)},
        )

    # ------------------------------------------------------------ holds ---

    async def hold(
        self,
        *,
        event: Event,
        user_id: uuid.UUID,
        items: Sequence[RequestedItem],
        now: datetime | None = None,
    ) -> list[HeldItem]:
        """Reserve inventory for a customer who is about to pay.

        Caller owns the transaction. This method flushes but never commits, so
        the hold and the booking that depends on it land together.

        On partial failure every hold taken in this call is released before
        raising — leaving three of four categories held would silently remove
        stock from sale until the sweeper noticed.
        """
        now = now or datetime.now(UTC)
        self._assert_on_sale(event, now)

        expires_at = now + timedelta(seconds=self.hold_seconds)
        requested_total = sum(item.quantity for item in items)
        if requested_total <= 0:
            raise BusinessRuleError("Select at least one ticket.", code="NO_TICKETS")

        await self._assert_within_purchase_limit(
            event=event, user_id=user_id, requested=requested_total, now=now
        )

        held: list[HeldItem] = []
        try:
            for item in items:
                held.append(
                    await self._hold_one(
                        event=event,
                        user_id=user_id,
                        item=item,
                        expires_at=expires_at,
                    )
                )
        except Exception:
            await self._release_items(held)
            raise

        return held

    async def _hold_one(
        self,
        *,
        event: Event,
        user_id: uuid.UUID,
        item: RequestedItem,
        expires_at: datetime,
    ) -> HeldItem:
        category = await self.categories.get(item.ticket_category_id)
        if category is None or category.event_id != event.id:
            raise NotFoundError(
                "Ticket category not found for this event.", code="CATEGORY_NOT_FOUND"
            )
        if not category.is_active:
            raise BusinessRuleError(f"{category.name} is not on sale.", code="CATEGORY_INACTIVE")
        if item.quantity < category.min_per_booking:
            raise BusinessRuleError(
                f"{category.name} requires at least {category.min_per_booking} ticket(s).",
                code="BELOW_MINIMUM",
            )
        if item.quantity > category.max_per_booking:
            raise BusinessRuleError(
                f"{category.name} allows at most {category.max_per_booking} ticket(s) per booking.",
                code="ABOVE_MAXIMUM",
            )

        # The one statement that decides. If it affects no rows the tickets
        # went to somebody else between the page load and this request —
        # which at a two-minute sellout is the normal outcome, not an error.
        if not await self.inventory.try_hold(category.id, item.quantity):
            raise ConflictError(
                f"{category.name} does not have {item.quantity} ticket(s) left.",
                code="INSUFFICIENT_INVENTORY",
                details={"ticket_category_id": str(category.id)},
            )

        reservation = TicketReservation(
            event_id=event.id,
            ticket_category_id=category.id,
            user_id=user_id,
            quantity=item.quantity,
            status=ReservationStatus.HELD,
            expires_at=expires_at,
        )
        self.reservations.add(reservation)
        await self.session.flush()

        # Read back after the UPDATE so the price snapshot matches the row we
        # actually decremented.
        await self.session.refresh(category)
        return HeldItem(
            reservation_id=reservation.id,
            ticket_category=category,
            quantity=item.quantity,
            unit_price_paise=category.price_paise,
        )

    async def _release_items(self, held: Sequence[HeldItem]) -> None:
        for item in held:
            await self.inventory.release_hold(item.ticket_category.id, item.quantity)
            reservation = await self.reservations.get(item.reservation_id)
            if reservation is not None and reservation.status is ReservationStatus.HELD:
                reservation.status = ReservationStatus.RELEASED
                reservation.released_at = datetime.now(UTC)

    # ------------------------------------------------- lifecycle changes ---

    async def attach_to_booking(
        self, reservation_ids: Sequence[uuid.UUID], booking_id: uuid.UUID
    ) -> None:
        for reservation_id in reservation_ids:
            reservation = await self.reservations.get(reservation_id)
            if reservation is not None:
                reservation.booking_id = booking_id

    async def commit_for_booking(self, booking_id: uuid.UUID) -> bool:
        """Turn this booking's holds into sales.

        Returns False if the holds are gone — the expiry sweeper got there
        first, which is the "payment succeeded after the hold expired" case.
        The caller then decides between re-allocating and refunding.
        """
        now = datetime.now(UTC)
        reservations = await self.reservations.for_booking(booking_id)
        live = [r for r in reservations if r.status is ReservationStatus.HELD]
        if not live:
            return False

        for reservation in live:
            if not await self.inventory.commit_hold(
                reservation.ticket_category_id, reservation.quantity
            ):
                return False

        await self.reservations.mark_converted(booking_id, now=now)
        return True

    async def reacquire_for_booking(self, booking_id: uuid.UUID) -> bool:
        """Try to take the stock again after a hold expired.

        Used when a payment lands late: if the tickets are still there the
        customer keeps them, and only if they are genuinely gone does the
        refund path start.
        """
        reservations = await self.reservations.for_booking(booking_id)
        expired = [r for r in reservations if r.status is ReservationStatus.EXPIRED]
        if not expired:
            return False

        taken: list[TicketReservation] = []
        for reservation in expired:
            if not await self.inventory.try_hold(
                reservation.ticket_category_id, reservation.quantity
            ):
                # Roll back whatever this attempt managed to take.
                for undo in taken:
                    await self.inventory.release_hold(undo.ticket_category_id, undo.quantity)
                return False
            taken.append(reservation)

        now = datetime.now(UTC)
        for reservation in taken:
            reservation.status = ReservationStatus.HELD
            reservation.released_at = None
            reservation.expires_at = now + timedelta(seconds=self.hold_seconds)
        await self.session.flush()
        return True

    async def release_for_booking(self, booking_id: uuid.UUID) -> int:
        """Return a pending booking's holds to sale. Safe to call twice."""
        now = datetime.now(UTC)
        reservations = await self.reservations.for_booking(booking_id)
        released = 0
        for reservation in reservations:
            if reservation.status is not ReservationStatus.HELD:
                continue
            if await self.inventory.release_hold(
                reservation.ticket_category_id, reservation.quantity
            ):
                reservation.status = ReservationStatus.RELEASED
                reservation.released_at = now
                released += reservation.quantity
        return released

    async def return_sold_for_booking(self, booking_id: uuid.UUID) -> int:
        """Put a cancelled booking's tickets back on sale."""
        items = await self.bookings.items(booking_id)
        returned = 0
        for item in items:
            if await self.inventory.return_sold(item.ticket_category_id, item.quantity):
                returned += item.quantity
        return returned

    async def sweep_expired(self, *, limit: int = 200) -> int:
        """Release holds that ran out. Run by the worker, on a short interval.

        Idempotent by construction: `claim_expired` moves rows HELD → EXPIRED
        in one statement with SKIP LOCKED, so a row is counted once however
        many sweepers are running.
        """
        now = datetime.now(UTC)
        expired = await self.reservations.claim_expired(now=now, limit=limit)
        released = 0
        for reservation in expired:
            if await self.inventory.release_hold(
                reservation.ticket_category_id, reservation.quantity
            ):
                released += reservation.quantity
        if expired:
            logger.info(
                "reservations_expired",
                reservations=len(expired),
                tickets_released=released,
            )
        return released

    # --------------------------------------------------------- guards ---

    @staticmethod
    def _assert_on_sale(event: Event, now: datetime) -> None:
        if event.status is EventStatus.CANCELLED:
            raise BusinessRuleError("This event has been cancelled.", code="EVENT_CANCELLED")
        if event.status not in (EventStatus.PUBLISHED, EventStatus.SOLD_OUT):
            raise NotFoundError("Event not found.", code="EVENT_NOT_FOUND")
        if event.sale_starts_at and now < event.sale_starts_at:
            raise BusinessRuleError(
                "Ticket sales have not opened yet.",
                code="SALE_NOT_OPEN",
                details={"sale_starts_at": event.sale_starts_at.isoformat()},
            )
        if event.sale_ends_at and now > event.sale_ends_at:
            raise BusinessRuleError("Ticket sales have closed.", code="SALE_CLOSED")
        if event.starts_at <= now:
            raise BusinessRuleError("This event has already started.", code="EVENT_STARTED")

    async def _assert_within_purchase_limit(
        self, *, event: Event, user_id: uuid.UUID, requested: int, now: datetime
    ) -> None:
        """Enforce the per-event limit across everything this customer holds.

        Counted over all their bookings and live holds, not per booking —
        a per-booking cap is defeated by booking twice, which is exactly what
        an automated buyer does.
        """
        # Serialise before reading. Read-then-write let two simultaneous
        # requests count the same existing bookings, both pass, and the
        # customer end up over the limit — and that limit is the control the
        # whole anti-bot plan rests on.
        #
        # Usually already held by the booking service; re-entrant, so taking
        # it again costs nothing and callers that reach `hold()` by another
        # route are still protected.
        await self.lock_customer_event(user_id, event.id)

        already = await self.bookings.purchased_quantity(user_id, event.id)
        holding = await self.reservations.live_for_user(user_id, event.id, now=now)
        limit = event.max_tickets_per_customer

        if already + holding + requested > limit:
            raise BusinessRuleError(
                f"You may book at most {limit} ticket(s) for this event.",
                code="PURCHASE_LIMIT_EXCEEDED",
                details={
                    "limit": limit,
                    "already_booked": already,
                    "currently_held": holding,
                    "requested": requested,
                },
            )
