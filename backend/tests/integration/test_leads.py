"""Enquiries and newsletter: the public forms, spam handling, and the admin inbox."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.conftest import customer_session, seed_admin, sign_in_as, unique_email
from tests.integration.google_stub import StubGoogleClient

pytestmark = pytest.mark.integration

ENQUIRIES = "/api/v1/enquiries"
SUBSCRIBE = "/api/v1/newsletter/subscribe"
UNSUBSCRIBE = "/api/v1/newsletter/unsubscribe"


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _enquiry(**over: object) -> dict[str, object]:
    return {
        "name": "  Priya Nair  ",
        "email": unique_email("lead").upper(),
        "phone": "+91 98765 43210",
        "event_date": (datetime.now(UTC) + timedelta(days=60)).date().isoformat(),
        "guests": 40,
        "message": "We would like to book the hall for a private listening evening.",
        **over,
    }


async def test_an_enquiry_is_stored_queued_for_the_team_and_visible_to_admins(
    api: AsyncClient, db_session: AsyncSession, google: StubGoogleClient
) -> None:
    body = _enquiry()
    sent = await api.post(ENQUIRIES, json=body)
    assert sent.status_code == 201 and sent.json() == {"ok": True}

    queued = (
        await db_session.execute(
            sa.text("SELECT count(*) FROM outbox_messages WHERE topic = 'enquiry.received'")
        )
    ).scalar_one()
    assert queued >= 1

    admin = await sign_in_as(api, google, await seed_admin(db_session))
    inbox = (await api.get("/api/v1/admin/enquiries", headers=bearer(admin))).json()
    mine = next(e for e in inbox["items"] if e["email"] == str(body["email"]).lower())
    assert mine["name"] == "Priya Nair" and mine["status"] == "NEW" and mine["guests"] == 40
    assert inbox["counts"].get("NEW", 0) >= 1

    updated = await api.patch(
        f"/api/v1/admin/enquiries/{mine['id']}",
        headers=bearer(admin),
        json={"status": "CONTACTED", "admin_note": "Called back, sending a quote."},
    )
    assert updated.status_code == 200 and updated.json()["status"] == "CONTACTED"
    only_new = (
        await api.get("/api/v1/admin/enquiries", params={"status": "NEW"}, headers=bearer(admin))
    ).json()
    assert mine["id"] not in [e["id"] for e in only_new["items"]]


async def test_bad_enquiries_and_bots_are_handled(
    api: AsyncClient, db_session: AsyncSession
) -> None:
    yesterday = (datetime.now(UTC) - timedelta(days=1)).date().isoformat()
    for bad in (
        _enquiry(message="too short"),
        _enquiry(email="not-an-email"),
        _enquiry(event_date=yesterday),
        _enquiry(guests=0),
        _enquiry(phone="call me maybe"),
    ):
        assert (await api.post(ENQUIRIES, json=bad)).status_code == 422

    # A bot that fills the hidden field gets the normal answer, and nothing is stored.
    bot_email = unique_email("bot")
    ok = await api.post(ENQUIRIES, json=_enquiry(email=bot_email, website="http://spam.example"))
    assert ok.status_code == 201
    stored = (
        await db_session.execute(
            sa.text("SELECT count(*) FROM enquiries WHERE email = :e"), {"e": bot_email.lower()}
        )
    ).scalar_one()
    assert stored == 0


async def test_newsletter_signup_unsubscribe_and_resubscribe(
    api: AsyncClient, db_session: AsyncSession, google: StubGoogleClient
) -> None:
    email = unique_email("news")
    first = await api.post(SUBSCRIBE, json={"email": email.upper()})
    again = await api.post(SUBSCRIBE, json={"email": email})
    assert first.json() == again.json() == {"ok": True}  # identical answer either way
    rows = (
        await db_session.execute(
            sa.text(
                "SELECT subscribed, unsubscribe_token FROM newsletter_subscribers WHERE email = :e"
            ),
            {"e": email.lower()},
        )
    ).all()
    assert len(rows) == 1 and rows[0][0] is True
    welcomes = (
        await db_session.execute(
            sa.text(
                "SELECT count(*) FROM outbox_messages WHERE topic = 'newsletter.subscribed' "
                "AND payload->>'subscriber_id' = "
                "(SELECT id::text FROM newsletter_subscribers WHERE email = :e)"
            ),
            {"e": email.lower()},
        )
    ).scalar_one()
    assert welcomes == 1  # the second signup did not send a second welcome

    token = rows[0][1]
    assert (
        await api.post(UNSUBSCRIBE, json={"token": "x" * 30})
    ).status_code == 200  # unknown: no leak
    assert (await api.post(UNSUBSCRIBE, json={"token": token})).status_code == 200
    state = (
        await db_session.execute(
            sa.text("SELECT subscribed FROM newsletter_subscribers WHERE email = :e"),
            {"e": email.lower()},
        )
    ).scalar_one()
    assert state is False

    admin = await sign_in_as(api, google, await seed_admin(db_session))
    listed = (
        await api.get(
            "/api/v1/admin/subscribers", params={"search": email[:8]}, headers=bearer(admin)
        )
    ).json()
    assert listed["items"][0]["subscribed"] is False

    await api.post(SUBSCRIBE, json={"email": email})  # coming back is allowed
    back = (
        await db_session.execute(
            sa.text("SELECT subscribed FROM newsletter_subscribers WHERE email = :e"),
            {"e": email.lower()},
        )
    ).scalar_one()
    assert back is True


async def test_subscriber_export_only_lists_subscribed_addresses_and_is_audited(
    api: AsyncClient, db_session: AsyncSession, google: StubGoogleClient
) -> None:
    keep, gone = unique_email("keep"), unique_email("gone")
    await api.post(SUBSCRIBE, json={"email": keep})
    await api.post(SUBSCRIBE, json={"email": gone})
    token = (
        await db_session.execute(
            sa.text("SELECT unsubscribe_token FROM newsletter_subscribers WHERE email = :e"),
            {"e": gone.lower()},
        )
    ).scalar_one()
    await api.post(UNSUBSCRIBE, json={"token": token})

    admin = await sign_in_as(api, google, await seed_admin(db_session))
    csv_response = await api.get("/api/v1/admin/subscribers.csv", headers=bearer(admin))
    text = csv_response.content.decode("utf-8-sig")
    assert csv_response.status_code == 200 and text.splitlines()[0] == "Email"
    assert keep.lower() in text and gone.lower() not in text
    audited = (
        await db_session.execute(
            sa.text(
                "SELECT count(*) FROM audit_logs WHERE action = 'newsletter.subscribers_exported'"
            )
        )
    ).scalar_one()
    assert audited >= 1


async def test_the_inbox_is_admin_only(api: AsyncClient, google: StubGoogleClient) -> None:
    customer = await customer_session(api, google)
    for path in ("enquiries", "subscribers", "subscribers.csv"):
        url = f"/api/v1/admin/{path}"
        assert (await api.get(url)).status_code == 401
        assert (await api.get(url, headers=bearer(customer["access"]))).status_code == 403
