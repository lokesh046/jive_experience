"""Bookings left before paying: a single, polite email asking them to come back.

A hold lasts a few minutes, so by the time someone could be reminded the seats are back on sale.
The email therefore says so plainly and makes no promise to keep anything for them.

Rules, all checked twice (when queued and again when sent):

* only online bookings the customer made themselves, and only once per booking;
* not if they have since bought for that event, or were already reminded about it in the last day;
* only while the event is on sale and the tickets they wanted are still available;
* never to a throwaway account (counter sales without an email).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import structlog
from sqlalchemy import and_, exists, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.commerce import Booking, BookingSource, BookingStatus
from app.models.event import Event, EventStatus
from app.models.user import User, UserStatus
from app.repositories.site_setting import SiteSettingRepository
from app.services.outbox import TOPIC_BOOKING_ABANDONED, OutboxService

logger = structlog.get_logger(__name__)

SETTING_KEY = "abandoned_emails"
WAIT = timedelta(minutes=30)  # long enough to have changed their mind, short enough to matter
WINDOW = timedelta(hours=24)  # older than this and the moment has passed
PER_EVENT_COOLDOWN = timedelta(hours=24)


async def abandoned_emails_enabled(session: AsyncSession) -> bool:
    stored = await SiteSettingRepository(session).get(SETTING_KEY)
    return True if stored is None else bool(stored.get("enabled", True))


class AbandonedBookingService:
    def __init__(self, session: AsyncSession, outbox: OutboxService) -> None:
        self.session = session
        self.outbox = outbox

    async def queue_due(self, now: datetime, *, limit: int = 100) -> int:
        """Queue a reminder for each booking that has just crossed the waiting time."""
        if not await abandoned_emails_enabled(self.session):
            return 0

        other = Booking.__table__.alias("other")
        bought = exists().where(
            and_(
                other.c.user_id == Booking.user_id,
                other.c.event_id == Booking.event_id,
                other.c.status.in_(
                    [
                        BookingStatus.CONFIRMED.value,
                        BookingStatus.PARTIALLY_REFUNDED.value,
                        BookingStatus.PENDING.value,
                    ]
                ),
            )
        )
        reminded = exists().where(
            and_(
                other.c.user_id == Booking.user_id,
                other.c.event_id == Booking.event_id,
                other.c.abandoned_notified_at > now - PER_EVENT_COOLDOWN,
            )
        )
        statement = (
            select(Booking)
            .join(Event, Event.id == Booking.event_id)
            .join(User, User.id == Booking.user_id)
            .where(
                Booking.status == BookingStatus.EXPIRED,
                Booking.source == BookingSource.ONLINE,
                Booking.issued_by_id.is_(None),
                Booking.abandoned_notified_at.is_(None),
                Booking.expires_at.is_not(None),
                Booking.expires_at < now - WAIT,
                Booking.expires_at > now - WINDOW,
                Event.status == EventStatus.PUBLISHED,
                Event.starts_at > now,
                or_(Event.sale_ends_at.is_(None), Event.sale_ends_at > now),
                or_(Event.sale_starts_at.is_(None), Event.sale_starts_at <= now),
                User.status == UserStatus.ACTIVE,
                ~User.email.like("%.invalid"),
                ~bought,
                ~reminded,
            )
            .order_by(Booking.expires_at)
            .limit(limit)
            .with_for_update(skip_locked=True, of=Booking)
        )
        rows = (await self.session.execute(statement)).scalars().all()
        queued = 0
        reminded_for: set[tuple[uuid.UUID, uuid.UUID]] = set()
        for booking in rows:
            key = (booking.user_id, booking.event_id)
            await self.session.execute(
                update(Booking).where(Booking.id == booking.id).values(abandoned_notified_at=now)
            )
            if key in reminded_for:
                continue  # a second abandoned attempt for the same night: remind once
            reminded_for.add(key)
            await self.outbox.enqueue(
                topic=TOPIC_BOOKING_ABANDONED,
                payload={"booking_id": str(booking.id)},
                dedup_key=f"{TOPIC_BOOKING_ABANDONED}:{booking.id}",
            )
            queued += 1
        await self.session.commit()
        return queued
