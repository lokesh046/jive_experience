"""Sales numbers for administrators."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.repositories.reports import ReportRepository
from app.schemas.reports import (
    SalesCategoryRow,
    SalesDay,
    SalesEventRow,
    SalesReport,
    SalesTotals,
)


class ReportService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.settings = settings
        self.reports = ReportRepository(session)

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
