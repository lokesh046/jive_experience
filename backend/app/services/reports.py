"""Sales numbers for administrators."""

from __future__ import annotations

import csv
import io
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import NotFoundError
from app.core.pagination import PageParams
from app.models.fulfilment import TicketStatus
from app.models.user import User
from app.repositories.catalogue import EventRepository
from app.repositories.reports import ReportRepository
from app.schemas.reports import (
    AttendeeOut,
    SalesCategoryRow,
    SalesDay,
    SalesEventRow,
    SalesReport,
    SalesTotals,
    ScanOut,
)
from app.services.audit import AuditService


class ReportService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.settings = settings
        self.session = session
        self.reports = ReportRepository(session)
        self.events = EventRepository(session)
        self.audit = AuditService(session)

    async def sales(self, *, days: int, event_id: uuid.UUID | None) -> SalesReport:
        zone = ZoneInfo(self.settings.default_timezone)
        today = datetime.now(zone).date()
        first_day = today - timedelta(days=days - 1)
        since = datetime.combine(first_day, time.min, tzinfo=zone).astimezone(UTC)

        events = await self.reports.events(event_id)
        booked = await self.reports.booking_totals()
        checked = await self.reports.checked_in()
        capacity = await self.reports.capacity()

        rows: list[SalesEventRow] = []
        for event in events:
            b = booked.get(event.id, {})
            gross, refunded = b.get("gross", 0), b.get("refunded", 0)
            rows.append(
                SalesEventRow(
                    event_id=event.id,
                    title=event.title,
                    slug=event.slug,
                    starts_at=event.starts_at,
                    status=event.status,
                    gross_paise=gross,
                    refunded_paise=refunded,
                    net_paise=gross - refunded,
                    tickets_sold=b.get("tickets", 0),
                    bookings=b.get("bookings", 0),
                    cancelled_bookings=b.get("cancelled", 0),
                    checked_in=checked.get(event.id, 0),
                    capacity=capacity.get(event.id, 0),
                )
            )

        summary = SalesTotals(
            gross_paise=sum(r.gross_paise for r in rows),
            refunded_paise=sum(r.refunded_paise for r in rows),
            net_paise=sum(r.net_paise for r in rows),
            tickets_sold=sum(r.tickets_sold for r in rows),
            bookings=sum(r.bookings for r in rows),
            cancelled_bookings=sum(r.cancelled_bookings for r in rows),
            checked_in=sum(r.checked_in for r in rows),
            capacity=sum(r.capacity for r in rows),
        )

        by_day = await self.reports.daily(since=since, timezone=zone.key, event_id=event_id)
        daily = [
            SalesDay(
                day=day,
                tickets=by_day.get(day, (0, 0))[0],
                gross_paise=by_day.get(day, (0, 0))[1],
            )
            for day in (first_day + timedelta(days=i) for i in range(days))
        ]

        categories = (
            [SalesCategoryRow(**c) for c in await self.reports.categories(event_id)]
            if event_id is not None
            else []
        )
        return SalesReport(
            summary=summary,
            events=rows,
            daily=daily,
            categories=categories,
            days=days,
            timezone=zone.key,
            generated_at=datetime.now(UTC),
        )

    # ------------------------------------------------- attendees & scans ---

    async def attendees(
        self,
        event_id: uuid.UUID,
        params: PageParams,
        *,
        status: TicketStatus | None,
        search: str | None,
    ) -> tuple[list[AttendeeOut], int]:
        await self.events.get_or_fail(event_id)
        rows, total = await self.reports.attendees(event_id, params, status=status, search=search)
        return [_attendee(row) for row in rows], total

    async def scans(self, event_id: uuid.UUID, params: PageParams) -> tuple[list[ScanOut], int]:
        await self.events.get_or_fail(event_id)
        rows, total = await self.reports.scans(event_id, params)
        return [
            ScanOut(
                scanned_at=r[0],
                result=r[1],
                serial=r[2],
                ticket_type=r[3],
                staff=r[4] or r[5],
                device_label=r[6],
            )
            for r in rows
        ], total

    async def attendees_csv(self, event_id: uuid.UUID, *, actor: User) -> tuple[str, bytes]:
        """Everyone holding a ticket, as a spreadsheet. Audited: it contains personal data."""
        event = await self.events.get(event_id)
        if event is None:
            raise NotFoundError("Event not found.", code="EVENT_NOT_FOUND")
        rows = await self.reports.attendees_all(event_id, MAX_EXPORT_ROWS)

        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(CSV_HEADER)
        for row in rows:
            a = _attendee(row)
            writer.writerow(
                [
                    _safe(cell)
                    for cell in (
                        a.serial,
                        a.ticket_type,
                        a.attendee_name or a.customer_name or "",
                        a.customer_name or "",
                        a.customer_email,
                        a.booking_reference,
                        a.status.value,
                        a.checked_in_at.isoformat() if a.checked_in_at else "",
                    )
                ]
            )
        await self.audit.record(
            "event.attendees_exported",
            entity_type="event",
            entity_id=event_id,
            actor=actor,
            after={"rows": len(rows)},
        )
        await self.session.commit()
        # A byte-order mark so Excel reads the file as UTF-8 (names with accents).
        return f"attendees-{event.slug}.csv", b"\xef\xbb\xbf" + out.getvalue().encode()


MAX_EXPORT_ROWS = 50_000
CSV_HEADER = [
    "Ticket",
    "Type",
    "Name on ticket",
    "Customer",
    "Email",
    "Booking",
    "Status",
    "Checked in at",
]


def _safe(value: str) -> str:
    """Spreadsheets run cells that start with = + - @ as formulas; defuse them."""
    return "'" + value if value[:1] in ("=", "+", "-", "@", "\t", "\r") else value


def _attendee(row: Sequence[object]) -> AttendeeOut:
    return AttendeeOut.model_validate(
        {
            "serial": row[0],
            "ticket_type": row[1],
            "status": row[2],
            "attendee_name": row[3],
            "customer_name": row[4],
            "customer_email": row[5],
            "booking_reference": row[6],
            "checked_in_at": row[7],
        }
    )
