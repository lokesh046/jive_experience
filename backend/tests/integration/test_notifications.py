"""Notifications: the bell and its API, the switches, and what each event tells whom."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import mailer
from app.core.config import Settings
from app.core.mailer import Mail
from app.models.user import User, UserRole, UserStatus
from app.services.notification import NotificationService
from app.services.notification_center import NotificationCenter
from app.services.notify_events import Notifier
from app.services.outbox import OutboxService
from app.services.ticket import TicketService
from tests.integration.conftest import (
    seed_admin,
    seed_staff,
    sign_in_as,
    unique_email,
)
from tests.integration.google_stub import StubGoogleClient
from tests.integration.test_review_fixes import _confirmed_booking_with_tickets, make_event

pytestmark = pytest.mark.integration

URL = "/api/v1/notifications"


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _tell(center: NotificationCenter, user: User, n: int = 1, **over: object) -> None:
    for i in range(n):
        args: dict[str, object] = {
            "kind": "booking.tickets_ready",
            "category": "bookings",
            "title": f"Note {i}",
            "dedup_key": f"k{uuid.uuid4().hex[:8]}",
            **over,
        }
        await center.notify([user.id], **args)  # type: ignore[arg-type]


async def _customer(session: AsyncSession) -> User:
    user = User(
        role=UserRole.CUSTOMER,
        status=UserStatus.ACTIVE,
        email=unique_email("cust"),
        full_name="Test Customer",
    )
    session.add(user)
    await session.flush()
    return user


async def _count(session: AsyncSession, **where: str) -> int:
    clause = " AND ".join(f"{k} = :{k}" for k in where) or "true"
    return int(
        (
            await session.execute(
                sa.text(f"SELECT count(*) FROM notifications WHERE {clause}"), where
            )
        ).scalar_one()
    )


# ------------------------------------------------------------------- the API ---


async def test_a_person_reads_pages_and_clears_only_their_own_notifications(
    api: AsyncClient, db_session: AsyncSession, google: StubGoogleClient
) -> None:
    assert (await api.get(URL)).status_code == 401
    me, them = await _customer(db_session), await _customer(db_session)
    await db_session.commit()
    mine = {"access": await sign_in_as(api, google, me)}
    other = {"access": await sign_in_as(api, google, them)}
    center = NotificationCenter(db_session)
    await _tell(center, me, 3)
    await _tell(center, them, 2)
    await db_session.commit()

    feed = (await api.get(URL, headers=bearer(mine["access"]), params={"limit": 2})).json()
    assert feed["unread"] == 3 and len(feed["items"]) == 2 and feed["next_before"]
    older = (
        await api.get(
            URL, headers=bearer(mine["access"]), params={"limit": 2, "before": feed["next_before"]}
        )
    ).json()
    assert len(older["items"]) == 1 and older["next_before"] is None
    assert (await api.get(f"{URL}/unread", headers=bearer(mine["access"]))).json() == {"unread": 3}

    # Another person's id is simply not theirs to mark.
    foreign = await api.post(
        f"{URL}/read",
        headers=bearer(mine["access"]),
        json={
            "ids": [(await api.get(URL, headers=bearer(other["access"]))).json()["items"][0]["id"]]
        },
    )
    assert foreign.json() == {"unread": 3}
    assert (await api.get(f"{URL}/unread", headers=bearer(other["access"]))).json() == {"unread": 2}

    one = await api.post(
        f"{URL}/read", headers=bearer(mine["access"]), json={"ids": [feed["items"][0]["id"]]}
    )
    assert one.json() == {"unread": 2}
    assert (await api.post(f"{URL}/read-all", headers=bearer(mine["access"]))).json() == {
        "unread": 0
    }
    assert (await api.get(f"{URL}/unread", headers=bearer(other["access"]))).json() == {"unread": 2}
    unread_only = await api.get(URL, headers=bearer(mine["access"]), params={"unread_only": True})
    assert unread_only.json()["items"] == []


async def test_each_role_sees_its_own_groups_and_can_switch_them(
    api: AsyncClient, db_session: AsyncSession, google: StubGoogleClient
) -> None:
    cust = await _customer(db_session)
    await db_session.commit()
    customer = {"access": await sign_in_as(api, google, cust)}
    groups = {
        p["category"]: p
        for p in (await api.get(f"{URL}/preferences", headers=bearer(customer["access"]))).json()
    }
    assert set(groups) == {"bookings", "reminders", "waitlist"}
    assert groups["reminders"]["email"] is True and groups["bookings"]["email_choice"] is False

    changed = await api.put(
        f"{URL}/preferences",
        headers=bearer(customer["access"]),
        json={
            "changes": [
                {"category": "reminders", "email": False},
                {"category": "waitlist", "in_app": False},
            ]
        },
    )
    by = {p["category"]: p for p in changed.json()}
    assert by["reminders"]["email"] is False and by["waitlist"]["in_app"] is False

    # Ticket and refund emails are not optional; admin groups are not a customer's to touch.
    assert (
        await api.put(
            f"{URL}/preferences",
            headers=bearer(customer["access"]),
            json={"changes": [{"category": "bookings", "email": False}]},
        )
    ).status_code == 422
    assert (
        await api.put(
            f"{URL}/preferences",
            headers=bearer(customer["access"]),
            json={"changes": [{"category": "payments", "in_app": False}]},
        )
    ).status_code == 404

    admin = await sign_in_as(api, google, await seed_admin(db_session))
    admin_groups = {
        p["category"] for p in (await api.get(f"{URL}/preferences", headers=bearer(admin))).json()
    }
    assert {"payments", "sales", "enquiries", "system", "gate"} <= admin_groups


# ---------------------------------------------------------------- the center ---


async def test_the_same_event_never_notifies_a_person_twice(db_session: AsyncSession) -> None:
    admin = await seed_admin(db_session)
    center = NotificationCenter(db_session)
    first = await center.notify(
        [admin.id], kind="x", category="system", title="One", dedup_key="same"
    )
    again = await center.notify(
        [admin.id], kind="x", category="system", title="One", dedup_key="same"
    )
    assert (first, again) == (1, 0)
    with pytest.raises(ValueError):
        await center.notify(
            [admin.id], kind="x", category="system", title="Bad", link="https://evil.test"
        )
    with pytest.raises(ValueError):
        await center.notify([admin.id], kind="x", category="nope", title="Bad")


async def test_switches_decide_what_reaches_the_bell_and_the_inbox(
    db_session: AsyncSession,
) -> None:
    admin = await seed_admin(db_session)
    quiet = await seed_admin(db_session)
    center = NotificationCenter(db_session)
    await db_session.commit()
    # `quiet` turns the bell off for payments; `admin` keeps the default (bell on, email on).
    await center.preferences.put(quiet.id, "payments", "in_app", False)
    await db_session.commit()
    n = await center.notify_admins(
        kind="p", category="payments", severity="critical", title="A refund failed", dedup_key="r1"
    )
    await db_session.commit()
    assert n >= 1
    assert await _count(db_session, user_id=str(admin.id)) == 1
    assert await _count(db_session, user_id=str(quiet.id)) == 0
    emails = (
        await db_session.execute(
            sa.text("SELECT count(*) FROM outbox_messages WHERE topic = 'notification.email'")
        )
    ).scalar_one()
    assert emails >= 1


async def test_suspended_admins_and_unassigned_staff_are_left_out(db_session: AsyncSession) -> None:
    event, _ = await make_event(db_session)
    active = await seed_admin(db_session)
    gone = await seed_admin(db_session)
    gone.status = UserStatus.SUSPENDED
    on_shift, off_shift = await seed_staff(db_session), await seed_staff(db_session)
    await db_session.execute(
        sa.text("INSERT INTO staff_event_assignments (user_id, event_id) VALUES (:u, :e)"),
        {"u": on_shift.id, "e": event.id},
    )
    await db_session.commit()
    center = NotificationCenter(db_session)
    await center.notify_admins(
        kind="s", category="system", title="Only active admins", dedup_key="a1"
    )
    await center.notify_event_staff(
        event.id, kind="g", category="gate", title="Doors", dedup_key="d1"
    )
    await db_session.commit()
    assert await _count(db_session, user_id=str(active.id)) >= 1
    assert await _count(db_session, user_id=str(gone.id)) == 0
    assert await _count(db_session, user_id=str(on_shift.id), kind="g") == 1
    assert await _count(db_session, user_id=str(off_shift.id)) == 0


async def test_old_notifications_are_cleared_but_recent_ones_stay(db_session: AsyncSession) -> None:
    admin = await seed_admin(db_session)
    center = NotificationCenter(db_session)
    await center.notify([admin.id], kind="o", category="system", title="Recent", dedup_key="recent")
    await center.notify(
        [admin.id], kind="o", category="system", title="Old read", dedup_key="oldread"
    )
    await center.notify(
        [admin.id], kind="o", category="system", title="Very old", dedup_key="veryold"
    )
    await db_session.execute(
        sa.text(
            "UPDATE notifications SET created_at = now() - interval '70 days', "
            "read_at = now() WHERE dedup_key = 'oldread'"
        )
    )
    await db_session.execute(
        sa.text(
            "UPDATE notifications SET created_at = now() - interval '200 days' "
            "WHERE dedup_key = 'veryold'"
        )
    )
    await db_session.commit()
    assert await center.prune() == 2
    await db_session.commit()
    assert await _count(db_session, user_id=str(admin.id), dedup_key="recent") == 1


# -------------------------------------------------------------- what is said ---


async def test_the_customer_hears_about_their_tickets_and_the_team_about_a_full_night(
    db_session: AsyncSession,
) -> None:
    customer, booking, event = await _confirmed_booking_with_tickets(db_session, 2)
    admin = await seed_admin(db_session)
    cid, ref, eid, aid = customer.id, booking.reference, event.id, admin.id
    await db_session.commit()
    notifier = Notifier(db_session)
    await notifier.tickets_ready(booking.id)
    await notifier.tickets_ready(booking.id)  # a retry says nothing new
    await db_session.commit()
    row = (
        await db_session.execute(
            sa.text("SELECT title, link, category FROM notifications WHERE user_id = :u"),
            {"u": cid},
        )
    ).one()
    assert row[1] == f"/tickets/{ref}" and row[2] == "bookings" and "are ready" in row[0]

    # 90% sold: one "filling" note; then sold out: one more, once.
    await db_session.execute(
        sa.text("UPDATE ticket_categories SET capacity = 10, sold_count = 9 WHERE event_id = :e"),
        {"e": eid},
    )
    await db_session.commit()
    await notifier.sales_progress(eid)
    await notifier.sales_progress(eid)
    await db_session.execute(
        sa.text("UPDATE ticket_categories SET sold_count = 10 WHERE event_id = :e"), {"e": eid}
    )
    await db_session.commit()
    await notifier.sales_progress(eid)
    await notifier.sales_progress(eid)
    await db_session.commit()
    kinds = [
        r[0]
        for r in (
            await db_session.execute(
                sa.text(
                    "SELECT kind FROM notifications WHERE user_id = :u AND category = 'sales' "
                    "ORDER BY created_at, kind"
                ),
                {"u": aid},
            )
        ).all()
    ]
    assert kinds == ["sales.filling", "sales.sold_out"]


async def test_gate_staff_hear_about_doors_once_and_admins_about_refused_tickets(
    db_session: AsyncSession,
) -> None:
    event, _ = await make_event(db_session)
    staff, admin = await seed_staff(db_session), await seed_admin(db_session)
    sid, aid, eid = staff.id, admin.id, event.id
    await db_session.execute(
        sa.text("INSERT INTO staff_event_assignments (user_id, event_id) VALUES (:u, :e)"),
        {"u": sid, "e": eid},
    )
    await db_session.execute(
        sa.text("UPDATE events SET starts_at = now() + interval '30 minutes' WHERE id = :e"),
        {"e": eid},
    )
    await db_session.commit()
    notifier = Notifier(db_session)
    assert await notifier.doors_open_soon(datetime.now(UTC)) >= 1
    assert await notifier.doors_open_soon(datetime.now(UTC)) == 0
    await notifier.suspicious_scan(eid, "JIVE-TEST-01", "ALREADY_USED")
    await db_session.commit()
    assert await _count(db_session, user_id=str(sid), kind="gate.doors_soon") == 1
    assert await _count(db_session, user_id=str(sid), kind="gate.refused_ticket") == 1
    assert await _count(db_session, user_id=str(aid), kind="gate.refused_ticket") == 1


# ------------------------------------------------------ emails that respect it ---


def _on(settings: Settings) -> Settings:
    return settings.model_copy(
        update={
            "smtp_host": "smtp.example.com",
            "smtp_username": "u",
            "smtp_password": SecretStr("p"),
            "mail_from": "alerts@example.com",
        }
    )


async def test_the_alert_email_carries_the_link_and_a_customer_can_opt_out_of_reminders(
    db_session: AsyncSession, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[Mail] = []

    async def capture(_s: Settings, mail: Mail) -> None:
        sent.append(mail)

    monkeypatch.setattr(mailer, "send_mail", capture)
    on = _on(settings)
    admin = await seed_admin(db_session)
    center = NotificationCenter(db_session)
    await center.notify(
        [admin.id],
        kind="r",
        category="payments",
        severity="critical",
        title="Refund failed",
        body="Provider said no",
        link="/admin/bookings",
        dedup_key="e1",
    )
    await db_session.commit()
    nid = (
        await db_session.execute(sa.text("SELECT id FROM notifications WHERE dedup_key = 'e1'"))
    ).scalar_one()
    service = NotificationService(
        db_session, on, TicketService(db_session, OutboxService(db_session), on)
    )
    assert await service.send_alert_email(nid) is True
    assert (
        sent[0].to == admin.email
        and "/admin/bookings" in sent[0].html
        and sent[0].subject == "[JIVE] Refund failed"
    )

    customer, booking, event = await _confirmed_booking_with_tickets(db_session, 1)
    await db_session.execute(
        sa.text("UPDATE events SET starts_at = now() + interval '12 hours' WHERE id = :e"),
        {"e": event.id},
    )
    await db_session.commit()
    sent.clear()
    assert await service.send_reminder(booking.id) is True  # on by default
    await center.preferences.put(customer.id, "reminders", "email", False)
    await db_session.commit()
    assert await service.send_reminder(booking.id) is False  # they turned it off
    assert sent and len(sent) == 1
    _ = timedelta, UserRole
