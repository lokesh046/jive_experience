"""Left before paying: who gets one reminder, who never does, and what it says."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import mailer
from app.core.config import Settings
from app.core.mailer import Mail
from app.models.commerce import Booking, BookingItem, BookingStatus
from app.models.event import Event, TicketCategory
from app.models.user import User, UserRole, UserStatus
from app.services.abandoned import AbandonedBookingService
from app.services.notification import NotificationService
from app.services.outbox import OutboxService
from app.services.ticket import TicketService
from tests.integration.conftest import unique_email
from tests.integration.test_review_fixes import make_event

pytestmark = pytest.mark.integration


def _on(settings: Settings) -> Settings:
    return settings.model_copy(
        update={
            "smtp_host": "smtp.example.com",
            "smtp_username": "u",
            "smtp_password": SecretStr("p"),
            "mail_from": "news@example.com",
        }
    )


@pytest.fixture(autouse=True)
async def clean(db_session: AsyncSession):  # type: ignore[no-untyped-def]
    await db_session.execute(sa.text("DELETE FROM site_settings WHERE key = 'abandoned_emails'"))
    await db_session.execute(
        sa.text("DELETE FROM outbox_messages WHERE topic = 'booking.abandoned'")
    )
    await db_session.commit()
    yield
    await db_session.execute(sa.text("DELETE FROM site_settings WHERE key = 'abandoned_emails'"))
    await db_session.commit()


async def _user(session: AsyncSession, *, email: str | None = None) -> User:
    user = User(
        role=UserRole.CUSTOMER,
        status=UserStatus.ACTIVE,
        email=email or unique_email("lost"),
        full_name="Meera Rao",
        phone_e164=f"+9190{uuid.uuid4().int % 10**8:08d}",
    )
    session.add(user)
    await session.flush()
    return user


async def _booking(
    session: AsyncSession,
    event: Event,
    category: TicketCategory,
    user: User,
    *,
    status: BookingStatus = BookingStatus.EXPIRED,
    expired_ago: timedelta = timedelta(hours=1),
    quantity: int = 2,
) -> Booking:
    booking = Booking(
        reference=f"JIVE-{uuid.uuid4().hex[:8].upper()}",
        user_id=user.id,
        event_id=event.id,
        status=status,
        subtotal_paise=category.price_paise * quantity,
        fees_paise=0,
        total_paise=category.price_paise * quantity,
        quantity=quantity,
        expires_at=datetime.now(UTC) - expired_ago,
    )
    session.add(booking)
    await session.flush()
    session.add(
        BookingItem(
            booking_id=booking.id,
            ticket_category_id=category.id,
            category_name=category.name,
            unit_price_paise=category.price_paise,
            quantity=quantity,
            line_total_paise=category.price_paise * quantity,
        )
    )
    await session.commit()
    return booking


def _queue(session: AsyncSession) -> AbandonedBookingService:
    return AbandonedBookingService(session, OutboxService(session))


async def _queued(session: AsyncSession) -> int:
    return int(
        (
            await session.execute(
                sa.text("SELECT count(*) FROM outbox_messages WHERE topic = 'booking.abandoned'")
            )
        ).scalar_one()
    )


async def test_one_reminder_per_booking_after_the_wait(db_session: AsyncSession) -> None:
    event, category = await make_event(db_session)
    user = await _user(db_session)
    await _booking(db_session, event, category, user)
    now = datetime.now(UTC)
    assert await _queue(db_session).queue_due(now) == 1
    assert await _queue(db_session).queue_due(now) == 0  # never twice
    assert await _queued(db_session) == 1


async def test_it_waits_thirty_minutes_and_gives_up_after_a_day(db_session: AsyncSession) -> None:
    event, category = await make_event(db_session)
    await _booking(
        db_session, event, category, await _user(db_session), expired_ago=timedelta(minutes=10)
    )
    await _booking(
        db_session, event, category, await _user(db_session), expired_ago=timedelta(hours=30)
    )
    assert await _queue(db_session).queue_due(datetime.now(UTC)) == 0


async def test_it_skips_counter_sales_throwaway_accounts_and_hold_only_sources(
    db_session: AsyncSession,
) -> None:
    event, category = await make_event(db_session)
    seller = await _user(db_session)
    counter = await _booking(db_session, event, category, await _user(db_session))
    await db_session.execute(
        sa.text("UPDATE bookings SET issued_by_id = :s WHERE id = :b"),
        {"s": seller.id, "b": counter.id},
    )
    await _booking(
        db_session, event, category, await _user(db_session, email="walkin-x@walk-in.invalid")
    )
    await db_session.commit()
    assert await _queue(db_session).queue_due(datetime.now(UTC)) == 0


async def test_it_skips_people_who_bought_since_or_were_just_reminded(
    db_session: AsyncSession,
) -> None:
    event, category = await make_event(db_session)
    bought = await _user(db_session)
    await _booking(db_session, event, category, bought)
    await _booking(
        db_session,
        event,
        category,
        bought,
        status=BookingStatus.CONFIRMED,
        expired_ago=timedelta(minutes=5),
    )
    # Two lapsed attempts for one night: a single reminder.
    twice = await _user(db_session)
    await _booking(db_session, event, category, twice)
    await _booking(db_session, event, category, twice, expired_ago=timedelta(hours=2))
    assert await _queue(db_session).queue_due(datetime.now(UTC)) == 1
    assert await _queue(db_session).queue_due(datetime.now(UTC)) == 0


async def test_it_skips_events_that_cannot_be_bought_any_more(db_session: AsyncSession) -> None:
    started, cat1 = await make_event(db_session)
    closed, cat2 = await make_event(db_session)
    await db_session.execute(
        sa.text("UPDATE events SET starts_at = now() - interval '1 hour' WHERE id = :i"),
        {"i": started.id},
    )
    await db_session.execute(
        sa.text("UPDATE events SET sale_ends_at = now() - interval '1 hour' WHERE id = :i"),
        {"i": closed.id},
    )
    await db_session.commit()
    await _booking(db_session, started, cat1, await _user(db_session))
    await _booking(db_session, closed, cat2, await _user(db_session))
    assert await _queue(db_session).queue_due(datetime.now(UTC)) == 0


async def test_an_admin_can_switch_it_off(db_session: AsyncSession) -> None:
    event, category = await make_event(db_session)
    await _booking(db_session, event, category, await _user(db_session))
    await db_session.execute(
        sa.text(
            "INSERT INTO site_settings (key, value) "
            "VALUES ('abandoned_emails', '{\"enabled\": false}')"
        )
    )
    await db_session.commit()
    assert await _queue(db_session).queue_due(datetime.now(UTC)) == 0


async def test_the_email_names_the_night_and_the_tickets_and_links_back(
    db_session: AsyncSession, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    event, category = await make_event(db_session)
    booking = await _booking(db_session, event, category, await _user(db_session))
    on = _on(settings)
    sent: list[Mail] = []

    async def capture(_s: Settings, mail: Mail) -> None:
        sent.append(mail)

    monkeypatch.setattr(mailer, "send_mail", capture)
    service = NotificationService(
        db_session, on, TicketService(db_session, OutboxService(db_session), on)
    )
    assert await service.send_abandoned(booking.id) is True
    mail = sent[0]
    assert "Review Fix Event" in mail.subject and "2 x General" in mail.text
    assert f"/events/{event.slug}#tickets" in mail.html and "cannot hold them" in mail.text


async def test_nothing_is_sent_when_it_would_no_longer_help(
    db_session: AsyncSession, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    event, category = await make_event(db_session, capacity=5)
    user = await _user(db_session)
    sold_out = await _booking(db_session, event, category, user)
    sold_out_id = sold_out.id
    later = await _user(db_session)
    bought_after = await _booking(db_session, event, category, later)
    on = _on(settings)
    sent: list[Mail] = []

    async def capture(_s: Settings, mail: Mail) -> None:
        sent.append(mail)

    monkeypatch.setattr(mailer, "send_mail", capture)
    service = NotificationService(
        db_session, on, TicketService(db_session, OutboxService(db_session), on)
    )

    # They bought in the meantime.
    await _booking(db_session, event, category, later, status=BookingStatus.CONFIRMED, quantity=1)
    assert await service.send_abandoned(bought_after.id) is False
    # The tickets they wanted are gone.
    await db_session.execute(
        sa.text("UPDATE ticket_categories SET sold_count = capacity WHERE id = :i"),
        {"i": category.id},
    )
    await db_session.commit()
    db_session.expire_all()  # the raw UPDATE bypassed the session's cached rows
    assert await service.send_abandoned(sold_out_id) is False
    assert sent == []
