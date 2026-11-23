"""Commerce queries.

The inventory statements here are the concurrency-critical part of the whole
system. They are written as single conditional UPDATEs rather than
read-then-write, so two simultaneous buyers of the last ticket cannot both
succeed — PostgreSQL serialises the row update and the loser's WHERE clause no
longer matches.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any, cast

from sqlalchemy import CursorResult, String, exists, func, select, update
from sqlalchemy import cast as sql_cast

from app.core.pagination import PageParams
from app.models.commerce import (
    Booking,
    BookingItem,
    BookingSource,
    BookingStatus,
    Payment,
    PaymentStatus,
    PaymentWebhookEvent,
    Refund,
    RefundStatus,
    ReservationStatus,
    TicketReservation,
)
from app.models.event import Event, EventStatus, TicketCategory
from app.models.fulfilment import OutboxMessage
from app.repositories.base import BaseRepository


class InventoryRepository(BaseRepository[TicketCategory]):
    """Atomic inventory movements.

    Every method is one statement. None of them read a value, decide, and then
    write it — that pattern is what oversells an event.
    """

    model = TicketCategory

    async def try_hold(self, ticket_category_id: uuid.UUID, quantity: int) -> bool:
        """Reserve `quantity` if that many are available.

        Returns False when the category sold out between the customer seeing
        availability and pressing Book — which at a two-minute sellout is the
        common case, not an edge case.
        """
        statement = (
            update(TicketCategory)
            .where(
                TicketCategory.id == ticket_category_id,
                TicketCategory.is_active.is_(True),
                # The whole correctness argument, in one clause.
                TicketCategory.capacity - TicketCategory.sold_count - TicketCategory.reserved_count
                >= quantity,
            )
            .values(reserved_count=TicketCategory.reserved_count + quantity)
        )
        result = cast("CursorResult[Any]", await self.session.execute(statement))
        return (result.rowcount or 0) == 1

    async def release_hold(self, ticket_category_id: uuid.UUID, quantity: int) -> bool:
        """Give held inventory back. Guarded so it can never go negative."""
        statement = (
            update(TicketCategory)
            .where(
                TicketCategory.id == ticket_category_id,
                TicketCategory.reserved_count >= quantity,
            )
            .values(reserved_count=TicketCategory.reserved_count - quantity)
        )
        result = cast("CursorResult[Any]", await self.session.execute(statement))
        return (result.rowcount or 0) == 1

    async def commit_hold(self, ticket_category_id: uuid.UUID, quantity: int) -> bool:
        """Turn a hold into a sale: reserved → sold, in one statement.

        The totals never change, so no other buyer can slip in between the
        decrement and the increment.
        """
        statement = (
            update(TicketCategory)
            .where(
                TicketCategory.id == ticket_category_id,
                TicketCategory.reserved_count >= quantity,
            )
            .values(
                reserved_count=TicketCategory.reserved_count - quantity,
                sold_count=TicketCategory.sold_count + quantity,
            )
        )
        result = cast("CursorResult[Any]", await self.session.execute(statement))
        return (result.rowcount or 0) == 1

    async def return_sold(self, ticket_category_id: uuid.UUID, quantity: int) -> bool:
        """Put sold inventory back on sale, after a cancellation or refund."""
        statement = (
            update(TicketCategory)
            .where(
                TicketCategory.id == ticket_category_id,
                TicketCategory.sold_count >= quantity,
            )
            .values(sold_count=TicketCategory.sold_count - quantity)
        )
        result = cast("CursorResult[Any]", await self.session.execute(statement))
        return (result.rowcount or 0) == 1

    async def availability(self, event_id: uuid.UUID) -> dict[uuid.UUID, int]:
        """Remaining tickets per category, for the availability endpoint."""
        statement = select(
            TicketCategory.id,
            TicketCategory.capacity - TicketCategory.sold_count - TicketCategory.reserved_count,
        ).where(TicketCategory.event_id == event_id)
        rows = (await self.session.execute(statement)).all()
        return {row[0]: int(row[1]) for row in rows}


class ReservationRepository(BaseRepository[TicketReservation]):
    model = TicketReservation

    async def claim_expired(
        self, *, now: datetime, limit: int = 200
    ) -> Sequence[TicketReservation]:
        """Atomically take ownership of expired holds.

        `FOR UPDATE SKIP LOCKED` lets several sweeper runs — or several worker
        processes — work the same queue without blocking each other or
        processing the same row twice.
        """
        subquery = (
            select(TicketReservation.id)
            .where(
                TicketReservation.status == ReservationStatus.HELD,
                TicketReservation.expires_at <= now,
            )
            .order_by(TicketReservation.expires_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
            .scalar_subquery()
        )
        statement = (
            update(TicketReservation)
            .where(TicketReservation.id.in_(subquery))
            .values(status=ReservationStatus.EXPIRED, released_at=now)
            .returning(TicketReservation)
        )
        return (await self.session.execute(statement)).scalars().all()

    async def for_booking(self, booking_id: uuid.UUID) -> Sequence[TicketReservation]:
        return await self.list(TicketReservation.booking_id == booking_id)

    async def live_for_user(self, user_id: uuid.UUID, event_id: uuid.UUID, *, now: datetime) -> int:
        """Tickets this customer currently holds for the event.

        Counted towards the per-event purchase limit so that opening twenty
        tabs does not get around it.
        """
        statement = select(func.coalesce(func.sum(TicketReservation.quantity), 0)).where(
            TicketReservation.user_id == user_id,
            TicketReservation.event_id == event_id,
            TicketReservation.status == ReservationStatus.HELD,
            TicketReservation.expires_at > now,
        )
        return int(await self.session.scalar(statement) or 0)

    async def mark_converted(self, booking_id: uuid.UUID, *, now: datetime) -> int:
        statement = (
            update(TicketReservation)
            .where(
                TicketReservation.booking_id == booking_id,
                TicketReservation.status == ReservationStatus.HELD,
            )
            .values(status=ReservationStatus.CONVERTED, released_at=now)
        )
        result = cast("CursorResult[Any]", await self.session.execute(statement))
        return result.rowcount or 0

    async def mark_released(self, booking_id: uuid.UUID, *, now: datetime) -> int:
        statement = (
            update(TicketReservation)
            .where(
                TicketReservation.booking_id == booking_id,
                TicketReservation.status == ReservationStatus.HELD,
            )
            .values(status=ReservationStatus.RELEASED, released_at=now)
        )
        result = cast("CursorResult[Any]", await self.session.execute(statement))
        return result.rowcount or 0


class BookingRepository(BaseRepository[Booking]):
    model = Booking

    async def by_reference(self, reference: str) -> Booking | None:
        return await self.find_one(Booking.reference == reference)

    async def by_idempotency_key(self, user_id: uuid.UUID, key: str) -> Booking | None:
        return await self.find_one(Booking.user_id == user_id, Booking.idempotency_key == key)

    async def reference_taken(self, reference: str) -> bool:
        return await self.exists(Booking.reference == reference)

    async def box_office_totals(
        self, event_id: uuid.UUID, *, seller_id: uuid.UUID | None
    ) -> list[tuple[uuid.UUID | None, str | None, str, int, int]]:
        """Confirmed counter sales, per seller and per way of paying.

        Rows are (seller id, seller name, source, tickets, paise).
        """
        from app.models.user import User

        stmt = (
            select(
                Booking.issued_by_id,
                User.full_name,
                Booking.source,
                func.sum(Booking.quantity),
                func.sum(Booking.total_paise),
            )
            .join(User, User.id == Booking.issued_by_id)
            .where(
                Booking.event_id == event_id,
                Booking.status == BookingStatus.CONFIRMED,
                Booking.issued_by_id.is_not(None),
                Booking.source.in_([BookingSource.CASH, BookingSource.ONLINE]),
            )
            .group_by(Booking.issued_by_id, User.full_name, Booking.source)
        )
        if seller_id is not None:
            stmt = stmt.where(Booking.issued_by_id == seller_id)
        rows = (await self.session.execute(stmt)).all()
        return [(row[0], row[1], row[2].value, int(row[3] or 0), int(row[4] or 0)) for row in rows]

    async def due_for_reminder(
        self, *, now: datetime, horizon: timedelta, limit: int = 500
    ) -> Sequence[uuid.UUID]:
        """Confirmed bookings whose event starts within `horizon` and which have
        not been queued for a reminder yet.

        A booking made inside the window is skipped: someone who bought a
        ticket this morning does not need a "tomorrow" email. Bookings already
        queued are excluded in SQL, not just de-duplicated on insert, so a
        large backlog cannot keep re-selecting the same first rows.
        """
        already = exists().where(
            OutboxMessage.dedup_key
            == func.concat("booking.reminder:", sql_cast(Booking.id, String))
        )
        statement = (
            select(Booking.id)
            .join(Event, Event.id == Booking.event_id)
            .where(
                Booking.status == BookingStatus.CONFIRMED,
                Event.status == EventStatus.PUBLISHED,
                Event.starts_at > now,
                Event.starts_at <= now + horizon,
                Booking.confirmed_at < Event.starts_at - horizon,
                ~already,
            )
            .order_by(Event.starts_at.asc())
            .limit(limit)
        )
        return (await self.session.execute(statement)).scalars().all()

    async def purchased_quantity(self, user_id: uuid.UUID, event_id: uuid.UUID) -> int:
        """Tickets already bought by this customer for this event.

        Counted across **all** their bookings — a per-booking limit is
        defeated by booking twice.
        """
        statement = select(func.coalesce(func.sum(Booking.quantity), 0)).where(
            Booking.user_id == user_id,
            Booking.event_id == event_id,
            # PENDING is deliberately absent. A pending booking's tickets are
            # still counted — by its live reservations, via
            # `ReservationRepository.live_for_user` — and counting the booking
            # here as well charged the customer's allowance twice, rejecting
            # legitimate top-ups inside the hold window.
            Booking.status.in_((BookingStatus.CONFIRMED, BookingStatus.PARTIALLY_REFUNDED)),
        )
        return int(await self.session.scalar(statement) or 0)

    async def list_for_user(
        self, user_id: uuid.UUID, params: PageParams
    ) -> tuple[Sequence[Booking], int]:
        return await self.paginate(
            params, Booking.user_id == user_id, order_by=[Booking.created_at.desc()]
        )

    async def list_admin(
        self,
        params: PageParams,
        *,
        event_id: uuid.UUID | None = None,
        status: BookingStatus | None = None,
        reference: str | None = None,
    ) -> tuple[Sequence[Booking], int]:
        where = []
        if event_id is not None:
            where.append(Booking.event_id == event_id)
        if status is not None:
            where.append(Booking.status == status)
        if reference:
            where.append(Booking.reference.ilike(f"%{reference}%"))
        return await self.paginate(params, *where, order_by=[Booking.created_at.desc()])

    async def claim_expired(self, *, now: datetime, limit: int = 200) -> Sequence[Booking]:
        """Pending bookings whose hold has run out."""
        subquery = (
            select(Booking.id)
            .where(
                Booking.status == BookingStatus.PENDING,
                Booking.expires_at.is_not(None),
                Booking.expires_at <= now,
            )
            .order_by(Booking.expires_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
            .scalar_subquery()
        )
        statement = (
            update(Booking)
            .where(Booking.id.in_(subquery))
            .values(status=BookingStatus.EXPIRED, cancelled_at=now)
            .returning(Booking)
        )
        return (await self.session.execute(statement)).scalars().all()

    async def confirm(self, booking_id: uuid.UUID, *, now: datetime) -> bool:
        """PENDING → CONFIRMED, exactly once.

        The status guard makes confirmation idempotent: a webhook and a
        browser redirect arriving together produce one confirmation, and the
        loser sees `False` and does nothing.
        """
        statement = (
            update(Booking)
            .where(Booking.id == booking_id, Booking.status == BookingStatus.PENDING)
            .values(status=BookingStatus.CONFIRMED, confirmed_at=now, expires_at=None)
        )
        result = cast("CursorResult[Any]", await self.session.execute(statement))
        return (result.rowcount or 0) == 1

    async def items(self, booking_id: uuid.UUID) -> Sequence[BookingItem]:
        statement = select(BookingItem).where(BookingItem.booking_id == booking_id)
        return (await self.session.execute(statement)).scalars().all()


class PaymentRepository(BaseRepository[Payment]):
    model = Payment

    async def by_provider_payment_id(
        self, provider: str, provider_payment_id: str
    ) -> Payment | None:
        return await self.find_one(
            Payment.provider == provider,
            Payment.provider_payment_id == provider_payment_id,
        )

    async def by_provider_order_id(self, provider: str, order_id: str) -> Payment | None:
        return await self.find_one(
            Payment.provider == provider, Payment.provider_order_id == order_id
        )

    async def by_idempotency_key(self, key: str) -> Payment | None:
        return await self.find_one(Payment.idempotency_key == key)

    async def for_booking(self, booking_id: uuid.UUID) -> Sequence[Payment]:
        return await self.list(
            Payment.booking_id == booking_id, order_by=[Payment.created_at.desc()]
        )

    async def captured_for_booking(self, booking_id: uuid.UUID) -> Payment | None:
        return await self.find_one(
            Payment.booking_id == booking_id, Payment.status == PaymentStatus.CAPTURED
        )

    async def mark_captured(
        self,
        payment_id: uuid.UUID,
        *,
        provider_payment_id: str,
        now: datetime,
        method: str | None = None,
    ) -> bool:
        """Move a payment to CAPTURED exactly once."""
        statement = (
            update(Payment)
            .where(
                Payment.id == payment_id,
                Payment.status.in_(
                    (
                        PaymentStatus.CREATED,
                        PaymentStatus.PENDING,
                        PaymentStatus.AUTHORIZED,
                        # FAILED is capturable on purpose. One order can carry
                        # several attempts — a declined card followed by a
                        # successful UPI — and this row tracks the order, not
                        # the attempt. Excluding FAILED meant the retry's
                        # money was taken while the booking stayed PENDING
                        # with no refund.
                        PaymentStatus.FAILED,
                    )
                ),
            )
            .values(
                status=PaymentStatus.CAPTURED,
                provider_payment_id=provider_payment_id,
                captured_at=now,
                method=method,
                # The earlier attempt's failure no longer describes this row.
                failure_reason=None,
                failed_at=None,
            )
        )
        result = cast("CursorResult[Any]", await self.session.execute(statement))
        return (result.rowcount or 0) == 1

    async def stale_in_flight(self, *, older_than: datetime, limit: int = 100) -> Sequence[Payment]:
        """Payments the gateway never finished telling us about.

        The reconciliation job asks the provider directly rather than waiting
        for a webhook that may never arrive.
        """
        return await self.list(
            Payment.status.in_(
                (PaymentStatus.CREATED, PaymentStatus.PENDING, PaymentStatus.AUTHORIZED)
            ),
            Payment.created_at <= older_than,
            order_by=[Payment.created_at.asc()],
            limit=limit,
        )


class WebhookEventRepository(BaseRepository[PaymentWebhookEvent]):
    model = PaymentWebhookEvent

    async def already_seen(self, provider: str, provider_event_id: str) -> bool:
        return await self.exists(
            PaymentWebhookEvent.provider == provider,
            PaymentWebhookEvent.provider_event_id == provider_event_id,
        )

    async def by_provider_event_id(
        self, provider: str, provider_event_id: str
    ) -> PaymentWebhookEvent | None:
        return await self.find_one(
            PaymentWebhookEvent.provider == provider,
            PaymentWebhookEvent.provider_event_id == provider_event_id,
        )


class RefundRepository(BaseRepository[Refund]):
    model = Refund

    async def for_booking(self, booking_id: uuid.UUID) -> Sequence[Refund]:
        return await self.list(Refund.booking_id == booking_id, order_by=[Refund.created_at.desc()])

    async def by_idempotency_key(self, key: str) -> Refund | None:
        return await self.find_one(Refund.idempotency_key == key)

    async def succeeded_total(self, booking_id: uuid.UUID) -> int:
        """Paise already refunded, so a second request cannot exceed the total."""
        statement = select(func.coalesce(func.sum(Refund.amount_paise), 0)).where(
            Refund.booking_id == booking_id, Refund.status == RefundStatus.SUCCEEDED
        )
        return int(await self.session.scalar(statement) or 0)

    async def in_flight(self, *, limit: int = 100) -> Sequence[Refund]:
        return await self.list(
            Refund.status.in_((RefundStatus.REQUESTED, RefundStatus.PROCESSING)),
            order_by=[Refund.created_at.asc()],
            limit=limit,
        )

    async def has_open_request(self, booking_id: uuid.UUID) -> bool:
        return await self.exists(
            Refund.booking_id == booking_id,
            Refund.status.in_((RefundStatus.REQUESTED, RefundStatus.PROCESSING)),
        )
