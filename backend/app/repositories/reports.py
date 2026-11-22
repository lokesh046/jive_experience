"""Read-only aggregate queries for the sales report.

"Sold" means a booking that was confirmed at some point: its payment captured.
A later cancellation or refund still counts as a sale in `gross`, and is taken
back out through `refunded`, so the report reconciles with the payment gateway.
Tickets and bookings that are still good are those CONFIRMED or PARTIALLY_REFUNDED.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date, datetime
from typing import Any

from sqlalchemy import Date, case, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import PageParams
from app.models.commerce import Booking, BookingItem, BookingStatus
from app.models.event import Event, EventStatus, TicketCategory
from app.models.fulfilment import CheckinResult, Ticket, TicketCheckin, TicketStatus
from app.models.user import User

ACTIVE = (BookingStatus.CONFIRMED, BookingStatus.PARTIALLY_REFUNDED)
GONE = (BookingStatus.CANCELLED, BookingStatus.REFUNDED)


class ReportRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def events(self, event_id: uuid.UUID | None) -> list[Event]:
        """Events worth reporting on: anything that has left draft."""
        statement = select(Event).where(Event.status != EventStatus.DRAFT)
        if event_id is not None:
            statement = select(Event).where(Event.id == event_id)
        statement = statement.order_by(Event.starts_at.desc()).limit(200)
        return list((await self.session.execute(statement)).scalars().all())

    async def booking_totals(self) -> dict[uuid.UUID, dict[str, int]]:
        sold = Booking.confirmed_at.is_not(None)
        statement = (
            select(
                Booking.event_id,
                func.coalesce(func.sum(case((sold, Booking.total_paise), else_=0)), 0),
                func.coalesce(func.sum(case((sold, Booking.refunded_paise), else_=0)), 0),
                func.coalesce(
                    func.sum(case((Booking.status.in_(ACTIVE), Booking.quantity), else_=0)), 0
                ),
                func.count(case((Booking.status.in_(ACTIVE), 1))),
                func.count(case((Booking.status.in_(GONE), 1))),
            )
            .where(sold)
            .group_by(Booking.event_id)
        )
        out: dict[uuid.UUID, dict[str, int]] = {}
        for event_id, gross, refunded, tickets, active, gone in (
            await self.session.execute(statement)
        ).all():
            out[event_id] = {
                "gross": int(gross),
                "refunded": int(refunded),
                "tickets": int(tickets),
                "bookings": int(active),
                "cancelled": int(gone),
            }
        return out

    async def checked_in(self) -> dict[uuid.UUID, int]:
        statement = (
            select(Ticket.event_id, func.count())
            .where(Ticket.status == TicketStatus.CHECKED_IN)
            .group_by(Ticket.event_id)
        )
        return {row[0]: int(row[1]) for row in (await self.session.execute(statement)).all()}

    async def capacity(self) -> dict[uuid.UUID, int]:
        statement = (
            select(TicketCategory.event_id, func.coalesce(func.sum(TicketCategory.capacity), 0))
            .where(TicketCategory.is_active.is_(True))
            .group_by(TicketCategory.event_id)
        )
        return {row[0]: int(row[1]) for row in (await self.session.execute(statement)).all()}

    async def daily(
        self, *, since: datetime, timezone: str, event_id: uuid.UUID | None
    ) -> dict[date, tuple[int, int]]:
        """Tickets and gross sales per calendar day in `timezone`."""
        day = cast(func.timezone(timezone, Booking.confirmed_at), Date)
        statement = (
            select(day, func.coalesce(func.sum(Booking.quantity), 0), func.sum(Booking.total_paise))
            .where(Booking.confirmed_at.is_not(None), Booking.confirmed_at >= since)
            .group_by(day)
        )
        if event_id is not None:
            statement = statement.where(Booking.event_id == event_id)
        return {
            row[0]: (int(row[1]), int(row[2] or 0))
            for row in (await self.session.execute(statement)).all()
        }

    async def categories(self, event_id: uuid.UUID) -> list[dict[str, Any]]:
        sales = (
            select(
                BookingItem.ticket_category_id.label("cid"),
                func.coalesce(func.sum(BookingItem.quantity), 0).label("qty"),
                func.coalesce(func.sum(BookingItem.line_total_paise), 0).label("gross"),
            )
            .join(Booking, Booking.id == BookingItem.booking_id)
            .where(Booking.event_id == event_id, Booking.status.in_(ACTIVE))
            .group_by(BookingItem.ticket_category_id)
            .subquery()
        )
        statement = (
            select(
                TicketCategory.name,
                TicketCategory.price_paise,
                TicketCategory.capacity,
                TicketCategory.is_active,
                func.coalesce(sales.c.qty, 0),
                func.coalesce(sales.c.gross, 0),
            )
            .outerjoin(sales, sales.c.cid == TicketCategory.id)
            .where(TicketCategory.event_id == event_id)
            .order_by(TicketCategory.sort_order, TicketCategory.name)
        )
        return [
            {
                "name": r[0],
                "price_paise": r[1],
                "capacity": r[2],
                "is_active": r[3],
                "tickets_sold": int(r[4]),
                "gross_paise": int(r[5]),
            }
            for r in (await self.session.execute(statement)).all()
        ]

    # ------------------------------------------------------- attendees ---

    def _attendee_query(
        self, event_id: uuid.UUID, status: TicketStatus | None, search: str | None
    ) -> Any:
        statement = (
            select(
                Ticket.serial,
                TicketCategory.name,
                Ticket.status,
                Ticket.attendee_name,
                User.full_name,
                User.email,
                Booking.reference,
                Ticket.checked_in_at,
                Booking.source,
            )
            .join(Booking, Booking.id == Ticket.booking_id)
            .join(User, User.id == Ticket.user_id)
            .join(TicketCategory, TicketCategory.id == Ticket.ticket_category_id)
            .where(Ticket.event_id == event_id)
        )
        if status is not None:
            statement = statement.where(Ticket.status == status)
        if search:
            term = search.strip()
            statement = statement.where(
                or_(
                    Ticket.serial.icontains(term, autoescape=True),
                    Booking.reference.icontains(term, autoescape=True),
                    User.email.icontains(term, autoescape=True),
                    User.full_name.icontains(term, autoescape=True),
                    Ticket.attendee_name.icontains(term, autoescape=True),
                )
            )
        return statement.order_by(TicketCategory.name, User.full_name, Ticket.serial)

    async def attendees(
        self,
        event_id: uuid.UUID,
        params: PageParams,
        *,
        status: TicketStatus | None,
        search: str | None,
    ) -> tuple[Sequence[tuple[Any, ...]], int]:
        query = self._attendee_query(event_id, status, search)
        total = (
            await self.session.execute(select(func.count()).select_from(query.subquery()))
        ).scalar_one()
        rows = (await self.session.execute(query.offset(params.offset).limit(params.limit))).all()
        return rows, int(total)

    async def attendees_all(self, event_id: uuid.UUID, limit: int) -> Sequence[tuple[Any, ...]]:
        query = self._attendee_query(event_id, None, None).limit(limit)
        return [tuple(r) for r in (await self.session.execute(query)).all()]

    async def scans(
        self, event_id: uuid.UUID, params: PageParams
    ) -> tuple[Sequence[tuple[Any, ...]], int]:
        staff = User.__table__.alias("staff")
        base = (
            select(
                TicketCheckin.scanned_at,
                TicketCheckin.result,
                Ticket.serial,
                TicketCategory.name,
                staff.c.full_name,
                staff.c.email,
                TicketCheckin.device_label,
            )
            .select_from(TicketCheckin)
            .outerjoin(Ticket, Ticket.id == TicketCheckin.ticket_id)
            .outerjoin(TicketCategory, TicketCategory.id == Ticket.ticket_category_id)
            .outerjoin(staff, staff.c.id == TicketCheckin.staff_user_id)
            .where(TicketCheckin.event_id == event_id)
        )
        total = (
            await self.session.execute(
                select(func.count()).select_from(
                    select(TicketCheckin.id).where(TicketCheckin.event_id == event_id).subquery()
                )
            )
        ).scalar_one()
        rows: Sequence[tuple[Any, ...]] = (
            await self.session.execute(
                base.order_by(TicketCheckin.scanned_at.desc())
                .offset(params.offset)
                .limit(params.limit)
            )
        ).all()
        return [tuple(r) for r in rows], int(total)


__all__ = ["CheckinResult", "ReportRepository"]
