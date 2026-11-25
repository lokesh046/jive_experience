"""Browser push: the message is what a browser can read, plus the rules around who gets it."""

from __future__ import annotations

import base64
import json
import threading
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from types import SimpleNamespace
from typing import Any

import http_ece
import jwt
import pytest
import sqlalchemy as sa
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from httpx import AsyncClient
from pydantic import SecretStr
from pywebpush import WebPushException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import webpush
from app.core.config import Settings
from app.core.errors import BusinessRuleError, ServiceUnavailableError
from app.core.webpush import Device, PushResult, send_push
from app.models.push_subscription import PushSubscription
from app.models.user import User, UserRole, UserStatus
from app.services.notification_center import NotificationCenter
from app.services.push import PushService
from tests.integration.conftest import seed_admin, sign_in_as, unique_email
from tests.integration.google_stub import StubGoogleClient

pytestmark = pytest.mark.integration


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _vapid() -> tuple[str, str]:
    key = ec.generate_private_key(ec.SECP256R1())
    private = key.private_numbers().private_value.to_bytes(32, "big")
    public = key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    return _b64(public), _b64(private)


def _on(settings: Settings) -> Settings:
    public, private = _vapid()
    return settings.model_copy(
        update={
            "vapid_public_key": public,
            "vapid_private_key": SecretStr(private),
            "vapid_subject": "mailto:push@example.com",
        }
    )


class _Browser:
    """What a browser holds for a push subscription: a key pair and an auth secret."""

    def __init__(self) -> None:
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.auth = base64.urlsafe_b64encode(b"0123456789abcdef").rstrip(b"=").decode()
        public = self.key.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
        )
        self.p256dh = _b64(public)


async def _customer(session: AsyncSession) -> User:
    user = User(
        role=UserRole.CUSTOMER,
        status=UserStatus.ACTIVE,
        email=unique_email("push"),
        full_name="Push Person",
    )
    session.add(user)
    await session.flush()
    return user


# ------------------------------------------------------------- the real message ---


def test_a_message_is_encrypted_and_signed_so_the_browser_can_read_it(
    settings: Settings,
) -> None:
    """Send to a local stand-in for the push service, then decrypt as the browser would."""
    got: dict[str, Any] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            got["body"] = self.rfile.read(int(self.headers["Content-Length"]))
            got["headers"] = {k.lower(): v for k, v in self.headers.items()}
            self.send_response(201)
            self.end_headers()

        def log_message(self, *args: object) -> None:
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    on = _on(settings)
    browser = _Browser()
    device = Device(
        endpoint=f"http://127.0.0.1:{server.server_port}/push/abc",
        p256dh=browser.p256dh,
        auth=browser.auth,
    )
    import asyncio

    try:
        result = asyncio.run(
            send_push(
                on, device, {"title": "Hello", "body": "World", "url": "/tickets"}, urgency="high"
            )
        )
    finally:
        server.shutdown()
    assert result is PushResult.SENT

    # The browser decrypts with its private key and the auth secret.
    padding = "=" * (-len(browser.auth) % 4)
    plain = http_ece.decrypt(
        got["body"],
        private_key=browser.key,
        auth_secret=base64.urlsafe_b64decode(browser.auth + padding),
        version="aes128gcm",
    )
    assert json.loads(plain) == {"title": "Hello", "body": "World", "url": "/tickets"}
    assert got["headers"]["urgency"] == "high" and got["headers"]["ttl"] == "86400"

    # The VAPID header proves the message came from this site: signed by our key.
    scheme, _, params = got["headers"]["authorization"].partition(" ")
    assert scheme.lower() == "vapid"
    fields = dict(p.strip().split("=", 1) for p in params.split(","))
    claims = jwt.decode(
        fields["t"],
        key=ec.EllipticCurvePublicKey.from_encoded_point(
            ec.SECP256R1(), base64.urlsafe_b64decode(fields["k"] + "=" * (-len(fields["k"]) % 4))
        ),
        algorithms=["ES256"],
        options={"verify_aud": False},
    )
    assert claims["sub"] == "mailto:push@example.com" and fields["k"] == on.vapid_public_key


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (410, PushResult.GONE),
        (404, PushResult.GONE),
        (503, PushResult.RETRY),
        (429, PushResult.RETRY),
        (400, PushResult.REFUSED),
    ],
)
async def test_what_the_push_service_says_decides_what_we_do(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, status: int, expected: PushResult
) -> None:
    def refuse(**_: object) -> None:
        raise WebPushException("no", response=SimpleNamespace(status_code=status))

    monkeypatch.setattr(webpush, "webpush", refuse)
    device = Device(endpoint="https://push.example/x", p256dh="p", auth="a")
    assert await send_push(_on(settings), device, {"title": "t"}) is expected


async def test_nothing_is_sent_when_push_is_not_set_up(settings: Settings) -> None:
    device = Device(endpoint="https://push.example/x", p256dh="p", auth="a")
    assert await send_push(settings, device, {"title": "t"}) is PushResult.REFUSED


# ------------------------------------------------------------------ the devices ---


async def test_a_device_belongs_to_whoever_turned_it_on_last_and_the_count_is_capped(
    db_session: AsyncSession, settings: Settings
) -> None:
    on = _on(settings)
    first, second = await _customer(db_session), await _customer(db_session)
    service = PushService(db_session, on)
    args = {"p256dh": "k" * 30, "auth": "a" * 12, "user_agent": "Chrome"}
    assert await service.subscribe(first, endpoint="https://push.example/shared", **args) == 1
    assert await service.subscribe(second, endpoint="https://push.example/shared", **args) == 1
    assert await service.device_count(first) == 0 and await service.device_count(second) == 1

    for i in range(10):
        await service.subscribe(first, endpoint=f"https://push.example/d{i}", **args)
    with pytest.raises(BusinessRuleError) as many:
        await service.subscribe(first, endpoint="https://push.example/one-too-many", **args)
    assert many.value.code == "TOO_MANY_DEVICES"
    await service.unsubscribe(first, endpoint="https://push.example/d0")
    assert await service.device_count(first) == 9


async def test_turning_on_is_refused_when_the_server_has_no_keys(
    db_session: AsyncSession, settings: Settings
) -> None:
    user = await _customer(db_session)
    with pytest.raises(ServiceUnavailableError):
        await PushService(db_session, settings).subscribe(
            user, endpoint="https://push.example/x", p256dh="k" * 30, auth="a" * 12, user_agent=None
        )


# ------------------------------------------------------------- who gets a push ---


async def test_only_people_with_a_device_and_the_group_on_get_a_push(
    db_session: AsyncSession, settings: Settings
) -> None:
    on = _on(settings)
    with_device, muted, no_device = [await _customer(db_session) for _ in range(3)]
    center = NotificationCenter(db_session)
    service = PushService(db_session, on)
    args = {"p256dh": "k" * 30, "auth": "a" * 12, "user_agent": None}
    await service.subscribe(with_device, endpoint="https://push.example/a", **args)
    await service.subscribe(muted, endpoint="https://push.example/b", **args)
    await center.preferences.put(muted.id, "bookings", "push", False)
    await db_session.commit()

    await center.notify(
        [with_device.id, muted.id, no_device.id],
        kind="booking.tickets_ready",
        category="bookings",
        title="Your tickets are ready",
        link="/tickets/JIVE-X",
        dedup_key="p1",
    )
    await db_session.commit()
    pushed = {
        str(r[0])
        for r in (
            await db_session.execute(
                sa.text(
                    "SELECT n.user_id FROM outbox_messages o JOIN notifications n "
                    "ON n.id = (o.payload->>'notification_id')::uuid "
                    "WHERE o.topic = 'notification.push' AND n.dedup_key = 'p1'"
                )
            )
        ).all()
    }
    assert pushed == {str(with_device.id)}


async def test_delivery_forgets_gone_devices_retries_busy_ones_and_gives_up_eventually(
    db_session: AsyncSession, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    on = _on(settings)
    user = await _customer(db_session)
    center = NotificationCenter(db_session)
    service = PushService(db_session, on)
    args = {"p256dh": "k" * 30, "auth": "a" * 12, "user_agent": None}
    await service.subscribe(user, endpoint="https://push.example/live", **args)
    await service.subscribe(user, endpoint="https://push.example/gone", **args)
    await center.notify(
        [user.id],
        kind="k",
        category="bookings",
        title="Hi",
        body="There",
        link="/tickets",
        dedup_key="d1",
    )
    await db_session.commit()
    nid = (
        await db_session.execute(sa.text("SELECT id FROM notifications WHERE dedup_key = 'd1'"))
    ).scalar_one()
    sent: list[dict[str, str]] = []

    async def fake(
        _s: Settings, device: Device, payload: dict[str, str], **_: object
    ) -> PushResult:
        sent.append(payload)
        return PushResult.GONE if device.endpoint.endswith("gone") else PushResult.SENT

    monkeypatch.setattr("app.services.push.send_push", fake)
    assert await service.deliver_notification(nid) == 1
    assert sent[0]["title"] == "Hi" and sent[0]["url"] == "/tickets"
    assert await service.device_count(user) == 1  # the gone one was forgotten

    async def busy(*_a: object, **_k: object) -> PushResult:
        return PushResult.RETRY

    monkeypatch.setattr("app.services.push.send_push", busy)
    with pytest.raises(ServiceUnavailableError):
        await service.deliver_notification(nid)  # nothing got through: the queue tries again
    for _ in range(4):
        with pytest.raises(ServiceUnavailableError):
            await service.deliver_notification(nid)
    assert await service.device_count(user) == 0  # five failures in a row: forgotten


# ----------------------------------------------------------------------- the API ---


async def test_the_api_hands_out_the_key_and_checks_who_is_subscribing(
    api: AsyncClient, db_session: AsyncSession, google: StubGoogleClient
) -> None:
    key = (await api.get("/api/v1/notifications/push/key")).json()
    assert key["configured"] is False and key["public_key"] is None  # the test server has no keys
    body = {
        "endpoint": "https://push.example/abcdefghij",
        "keys": {"p256dh": "k" * 30, "auth": "a" * 12},
    }
    assert (await api.post("/api/v1/notifications/push/subscribe", json=body)).status_code == 401
    admin = await sign_in_as(api, google, await seed_admin(db_session))
    headers = {"Authorization": f"Bearer {admin}"}
    assert (
        await api.post("/api/v1/notifications/push/subscribe", headers=headers, json=body)
    ).status_code == 503
    for bad in (
        {**body, "endpoint": "http://insecure.example/abcdefghijklmn"},
        {**body, "keys": {"p256dh": "short", "auth": "a" * 12}},
        {"endpoint": "https://push.example/abcdefghij"},
    ):
        assert (
            await api.post("/api/v1/notifications/push/subscribe", headers=headers, json=bad)
        ).status_code == 422
    assert uuid  # (kept for the helpers above)
    assert PushSubscription
