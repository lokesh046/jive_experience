"""Push to the phone app: Expo carries the message, and the same rules apply to who gets it."""

from __future__ import annotations

import httpx
import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import BusinessRuleError
from app.core.expopush import send_expo
from app.core.webpush import PushResult
from app.models.user import User, UserRole, UserStatus
from app.services.notification_center import NotificationCenter
from app.services.push import MAX_DEVICES, PushService
from tests.integration.conftest import seed_admin, sign_in_as, unique_email
from tests.integration.google_stub import StubGoogleClient

pytestmark = pytest.mark.integration

TOKEN = "ExponentPushToken[abcdefghijklmnopqrstuv]"


def _expo(handler: httpx.MockTransport) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=handler)


async def test_expo_replies_are_turned_into_what_to_do_next() -> None:
    seen: dict[str, object] = {}

    def ok(request: httpx.Request) -> httpx.Response:
        seen["body"] = request.content
        return httpx.Response(200, json={"data": {"status": "ok", "id": "x"}})

    payload = {"title": "Hi", "body": "There", "url": "/tickets/ABC", "tag": "n1"}
    async with _expo(httpx.MockTransport(ok)) as c:
        assert await send_expo(TOKEN, payload, client=c) is PushResult.SENT
    assert b'"/tickets/ABC"' in seen["body"]  # type: ignore[operator]

    async def reply(status: int, body: dict[str, object]) -> PushResult:
        async with _expo(httpx.MockTransport(lambda _r: httpx.Response(status, json=body))) as c:
            return await send_expo(TOKEN, payload, client=c)

    gone = {"data": {"status": "error", "details": {"error": "DeviceNotRegistered"}}}
    assert await reply(200, gone) is PushResult.GONE
    assert await reply(503, {}) is PushResult.RETRY
    assert await reply(429, {}) is PushResult.RETRY
    assert await reply(400, {}) is PushResult.REFUSED
    other = {"data": {"status": "error", "details": {"error": "InvalidCredentials"}}}
    assert await reply(200, other) is PushResult.REFUSED


async def test_a_phone_gets_the_push_even_when_the_server_has_no_browser_keys(
    db_session: AsyncSession, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = User(
        role=UserRole.CUSTOMER, status=UserStatus.ACTIVE, email=unique_email("phone"), full_name="P"
    )
    db_session.add(user)
    await db_session.flush()
    assert settings.push_configured is False
    service = PushService(db_session, settings)
    assert await service.subscribe_phone(user, token=TOKEN, platform="ios") == 1
    assert await service.subscribe_phone(user, token=TOKEN, platform="android") == 1  # same device
    await NotificationCenter(db_session).notify(
        [user.id],
        kind="k",
        category="bookings",
        title="Hi",
        body="There",
        link="/tickets",
        dedup_key="ph1",
    )
    await db_session.commit()
    nid = (
        await db_session.execute(sa.text("SELECT id FROM notifications WHERE dedup_key = 'ph1'"))
    ).scalar_one()
    sent: list[tuple[str, dict[str, str]]] = []

    async def fake(token: str, payload: dict[str, str], **_: object) -> PushResult:
        sent.append((token, payload))
        return PushResult.SENT

    monkeypatch.setattr("app.services.push.send_expo", fake)
    assert await service.deliver_notification(nid) == 1
    assert sent[0][0] == TOKEN and sent[0][1]["title"] == "Hi"

    async def gone(*_a: object, **_k: object) -> PushResult:
        return PushResult.GONE

    monkeypatch.setattr("app.services.push.send_expo", gone)
    assert await service.deliver_notification(nid) == 0
    assert await service.device_count(user) == 0  # Expo said the phone is gone: forgotten


async def test_a_person_can_only_register_so_many_phones(
    db_session: AsyncSession, settings: Settings
) -> None:
    user = User(
        role=UserRole.CUSTOMER, status=UserStatus.ACTIVE, email=unique_email("many"), full_name="M"
    )
    db_session.add(user)
    await db_session.flush()
    service = PushService(db_session, settings)
    for i in range(MAX_DEVICES):
        await service.subscribe_phone(
            user, token=f"ExponentPushToken[device{i:02d}xxxxxxxxxxxx]", platform="ios"
        )
    with pytest.raises(BusinessRuleError):
        await service.subscribe_phone(
            user, token="ExponentPushToken[oneTooMany0000000000]", platform="ios"
        )


async def test_the_phone_endpoint_needs_sign_in_and_a_real_token(
    api: AsyncClient, db_session: AsyncSession, google: StubGoogleClient
) -> None:
    body = {"token": TOKEN, "platform": "ios"}
    assert (await api.post("/api/v1/notifications/push/device", json=body)).status_code == 401
    token = await sign_in_as(api, google, await seed_admin(db_session))
    headers = {"Authorization": f"Bearer {token}"}
    ok = await api.post("/api/v1/notifications/push/device", headers=headers, json=body)
    assert ok.status_code == 201 and ok.json() == {"devices": 1}
    for bad in (
        {**body, "token": "not-a-token-at-all-really"},
        {**body, "platform": "windows"},
        {"token": TOKEN},
    ):
        assert (
            await api.post("/api/v1/notifications/push/device", headers=headers, json=bad)
        ).status_code == 422
