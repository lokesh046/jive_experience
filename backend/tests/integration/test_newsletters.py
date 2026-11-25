"""Newsletters: the email, the admin API, and sending to the list exactly once."""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import mailer
from app.core.config import Settings
from app.core.errors import BusinessRuleError
from app.core.mailer import Mail
from app.models.newsletter_campaign import NewsletterCampaign
from app.models.user import User
from app.schemas.newsletter import CampaignIn
from app.services.newsletter import NewsletterService
from app.services.newsletter_mail import build_campaign_mail
from app.services.notification import NotificationService
from app.services.outbox import OutboxService
from app.services.ticket import TicketService
from tests.integration.conftest import customer_session, seed_admin, sign_in_as, unique_email
from tests.integration.google_stub import StubGoogleClient
from tests.integration.test_review_fixes import make_event

pytestmark = pytest.mark.integration

URL = "/api/v1/admin/newsletters"


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


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
    for table in ("newsletter_campaigns", "newsletter_subscribers"):
        await db_session.execute(sa.text(f"DELETE FROM {table}"))
    await db_session.execute(sa.text("DELETE FROM outbox_messages WHERE topic = 'newsletter.send'"))
    await db_session.commit()


async def _subscribers(session: AsyncSession, n: int, *, unsubscribed: int = 0) -> list[uuid.UUID]:
    ids = []
    for i in range(n):
        sid = uuid.uuid4()
        await session.execute(
            sa.text(
                "INSERT INTO newsletter_subscribers (id, email, subscribed, unsubscribe_token) "
                "VALUES (:i, :e, :s, :t)"
            ),
            {"i": sid, "e": unique_email("sub"), "s": i >= unsubscribed, "t": uuid.uuid4().hex},
        )
        ids.append(sid)
    await session.commit()
    return ids


def _campaign(**over: object) -> CampaignIn:
    return CampaignIn(subject="New night announced", body="Doors at 7.\n\nSee you there.", **over)  # type: ignore[arg-type]


# --------------------------------------------------------------------- the email ---


async def test_the_email_escapes_text_and_carries_an_unsubscribe_link(
    db_session: AsyncSession, settings: Settings
) -> None:
    event, _ = await make_event(db_session)
    campaign = NewsletterCampaign(
        subject="Hi",
        body="<script>alert(1)</script>\nsecond line\n\nNew paragraph",
        event_id=event.id,
        button_label=None,
        button_url=None,
    )
    mail = build_campaign_mail(
        settings,
        campaign,
        event,
        to="a@b.com",
        unsubscribe_url="https://x.test/unsubscribe?token=t",
    )
    assert "<script>" not in mail.html and "&lt;script&gt;" in mail.html
    assert "second line" in mail.html and mail.html.count("<p style='margin:0 0 16px'>") == 2
    assert "Review Fix Event" in mail.html and "Get tickets" in mail.html  # the featured night
    assert "unsubscribe?token=t" in mail.html and "unsubscribe?token=t" in mail.text
    assert mail.headers["List-Unsubscribe"] == "<https://x.test/unsubscribe?token=t>"
    test = build_campaign_mail(
        settings, campaign, None, to="a@b.com", unsubscribe_url=None, test=True
    )
    assert test.subject == "[Test] Hi" and "List-Unsubscribe" not in test.headers


# ------------------------------------------------------------------------ the API ---


async def test_admins_write_edit_and_delete_drafts(
    api: AsyncClient, db_session: AsyncSession, google: StubGoogleClient
) -> None:
    admin = await sign_in_as(api, google, await seed_admin(db_session))
    made = await api.post(
        URL,
        headers=bearer(admin),
        json={
            "subject": "  Spring  ",
            "body": "Hello",
            "button_label": "Book",
            "button_url": "https://a.test/x",
        },
    )
    assert made.status_code == 201, made.text
    cid = made.json()["id"]
    assert made.json()["subject"] == "Spring" and made.json()["status"] == "DRAFT"
    edited = await api.put(
        f"{URL}/{cid}", headers=bearer(admin), json={"subject": "Summer", "body": "Hi"}
    )
    assert edited.json()["subject"] == "Summer" and edited.json()["button_label"] is None
    assert [c["subject"] for c in (await api.get(URL, headers=bearer(admin))).json()] == ["Summer"]
    assert (await api.delete(f"{URL}/{cid}", headers=bearer(admin))).status_code == 204
    assert (await api.get(f"{URL}/{cid}", headers=bearer(admin))).status_code == 404


async def test_bad_input_and_non_admins_are_refused(
    api: AsyncClient, db_session: AsyncSession, google: StubGoogleClient
) -> None:
    assert (await api.get(URL)).status_code == 401
    customer = await customer_session(api, google)
    assert (await api.get(URL, headers=bearer(customer["access"]))).status_code == 403
    admin = await sign_in_as(api, google, await seed_admin(db_session))
    for bad in (
        {"subject": "", "body": "x"},
        {"subject": "x", "body": "  "},
        {"subject": "x", "body": "y", "button_label": "Go"},  # a label with no link
        {"subject": "x", "body": "y", "button_label": "Go", "button_url": "javascript:alert(1)"},
        {"subject": "x" * 201, "body": "y"},
    ):
        assert (await api.post(URL, headers=bearer(admin), json=bad)).status_code == 422
    missing = await api.post(
        URL,
        headers=bearer(admin),
        json={"subject": "x", "body": "y", "event_id": str(uuid.uuid4())},
    )
    assert missing.status_code == 404


async def test_sending_is_refused_while_email_is_not_set_up(
    api: AsyncClient, db_session: AsyncSession, google: StubGoogleClient
) -> None:
    admin = await sign_in_as(api, google, await seed_admin(db_session))
    cid = (await api.post(URL, headers=bearer(admin), json={"subject": "x", "body": "y"})).json()[
        "id"
    ]
    for path in ("send", "test"):
        refused = await api.post(f"{URL}/{cid}/{path}", headers=bearer(admin))
        assert (
            refused.status_code == 503 and refused.json()["error"]["code"] == "EMAIL_NOT_CONFIGURED"
        )


# ----------------------------------------------------------------------- sending ---


def _service(session: AsyncSession, settings: Settings) -> NewsletterService:
    return NewsletterService(session, _on(settings), OutboxService(session))


async def _admin_user(session: AsyncSession) -> User:
    admin = await seed_admin(session)
    await session.commit()
    return admin


async def test_an_issue_is_queued_once_to_current_subscribers_only(
    db_session: AsyncSession, settings: Settings
) -> None:
    await _subscribers(db_session, 4, unsubscribed=1)
    actor = await _admin_user(db_session)
    service = _service(db_session, settings)
    campaign = await service.create(_campaign(), actor=actor)

    assert await service.send(campaign.id, actor=actor) == 3  # the unsubscribed one is skipped
    queued = (
        await db_session.execute(
            sa.text("SELECT count(*) FROM outbox_messages WHERE topic = 'newsletter.send'")
        )
    ).scalar_one()
    assert queued == 3
    await db_session.refresh(campaign)
    assert campaign.status == "SENT" and campaign.recipients == 3 and campaign.sent_at is not None

    # A second click, or an edit afterwards, changes nothing.
    with pytest.raises(BusinessRuleError) as again:
        await service.send(campaign.id, actor=actor)
    assert again.value.code == "CAMPAIGN_ALREADY_SENT"
    with pytest.raises(BusinessRuleError):
        await service.update(campaign.id, _campaign(), actor=actor)
    with pytest.raises(BusinessRuleError):
        await service.delete(campaign.id, actor=actor)
    assert (
        await db_session.execute(
            sa.text("SELECT count(*) FROM outbox_messages WHERE topic = 'newsletter.send'")
        )
    ).scalar_one() == 3

    # Progress is read from the queue.
    (row,) = [r for r in await service.list_with_progress() if r[0].id == campaign.id]
    assert (row[1], row[2]) == (3, 0)


async def test_nobody_subscribed_means_nothing_to_send(
    db_session: AsyncSession, settings: Settings
) -> None:
    actor = await _admin_user(db_session)
    service = _service(db_session, settings)
    campaign = await service.create(_campaign(), actor=actor)
    with pytest.raises(BusinessRuleError) as err:
        await service.send(campaign.id, actor=actor)
    assert err.value.code == "NO_SUBSCRIBERS"
    await db_session.refresh(campaign)
    assert campaign.status == "DRAFT"


async def test_the_worker_sends_each_copy_and_skips_anyone_who_left_since(
    db_session: AsyncSession, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    ids = await _subscribers(db_session, 2)
    actor = await _admin_user(db_session)
    on = _on(settings)
    campaign = await NewsletterService(db_session, on, OutboxService(db_session)).create(
        _campaign(), actor=actor
    )
    sent: list[Mail] = []

    async def capture(_settings: Settings, mail: Mail, **_: object) -> None:
        sent.append(mail)

    monkeypatch.setattr(mailer, "send_mail", capture)
    notifications = NotificationService(
        db_session, on, TicketService(db_session, OutboxService(db_session), on)
    )
    assert await notifications.send_campaign(campaign.id, ids[0]) is True
    assert len(sent) == 1 and "Unsubscribe" in sent[0].html and sent[0].headers["List-Unsubscribe"]

    await db_session.execute(
        sa.text("UPDATE newsletter_subscribers SET subscribed = false WHERE id = :i"), {"i": ids[1]}
    )
    await db_session.commit()
    assert await notifications.send_campaign(campaign.id, ids[1]) is False
    assert len(sent) == 1
    await db_session.commit()
    await db_session.refresh(campaign)
    assert campaign.delivered == 1


async def test_a_test_send_goes_only_to_the_administrator(
    db_session: AsyncSession, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _subscribers(db_session, 3)
    actor = await _admin_user(db_session)
    sent: list[Mail] = []

    async def capture(_settings: Settings, mail: Mail, **_: object) -> None:
        sent.append(mail)

    monkeypatch.setattr(mailer, "send_mail", capture)
    service = _service(db_session, settings)
    campaign = await service.create(_campaign(), actor=actor)
    assert await service.send_test(campaign.id, actor=actor) == actor.email
    assert [m.to for m in sent] == [actor.email] and sent[0].subject.startswith("[Test]")
    await db_session.refresh(campaign)
    assert campaign.status == "DRAFT"
