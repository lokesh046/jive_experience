"""Browser push: remembering which devices belong to whom, and sending to them.

Push is the third channel next to the bell and email. It is opt-in by action: a person gets
push only on a device where they pressed "turn on", and can switch each group off. Sending is a
queued job, so a slow or failing push service never delays the thing that caused the message.
"""

from __future__ import annotations

import uuid

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import BusinessRuleError, ServiceUnavailableError
from app.core.webpush import Device, PushResult, send_push
from app.models.notification import Notification
from app.models.push_subscription import PushSubscription
from app.models.user import User
from app.repositories.push import PushRepository

logger = structlog.get_logger(__name__)

GIVE_UP_AFTER = 5  # failures in a row that were not a clear "gone"
MAX_DEVICES = 10  # per person


class PushService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.devices = PushRepository(session)

    def _require(self) -> None:
        if not self.settings.push_configured:
            raise ServiceUnavailableError(
                "Browser notifications are not set up on this server.", code="PUSH_NOT_CONFIGURED"
            )

    async def subscribe(
        self, user: User, *, endpoint: str, p256dh: str, auth: str, user_agent: str | None
    ) -> int:
        self._require()
        mine = {d.endpoint for d in await self.devices.for_user(user.id)}
        if endpoint not in mine and len(mine) >= MAX_DEVICES:
            raise BusinessRuleError(
                "That is too many devices. Turn notifications off on one you no longer use.",
                code="TOO_MANY_DEVICES",
            )
        await self.devices.upsert(
            user_id=user.id,
            endpoint=endpoint,
            p256dh=p256dh,
            auth=auth,
            user_agent=(user_agent or "")[:300] or None,
        )
        await self.session.commit()
        return len(await self.devices.for_user(user.id))

    async def unsubscribe(self, user: User, *, endpoint: str) -> None:
        await self.devices.remove(user_id=user.id, endpoint=endpoint)
        await self.session.commit()

    async def device_count(self, user: User) -> int:
        return len(await self.devices.for_user(user.id))

    async def send_test(self, user: User) -> int:
        """A real push to this person's own devices, so they can see it works."""
        self._require()
        payload = {
            "title": "Notifications are on",
            "body": "This is how JIVE will tell you when something needs you.",
            "url": "/notifications",
            "tag": "test",
        }
        sent = 0
        for device in await self.devices.for_user(user.id):
            if await self._deliver(device, payload) is PushResult.SENT:
                sent += 1
        await self.session.commit()
        return sent

    async def deliver_notification(self, notification_id: uuid.UUID) -> int:
        """Push one notification to every device its owner turned on. Returns how many got it."""
        if not self.settings.push_configured:
            return 0
        note = await self.session.get(Notification, notification_id)
        if note is None:
            return 0
        devices = list(await self.devices.for_user(note.user_id))
        if not devices:
            return 0
        payload = {
            "title": note.title,
            "body": note.body or "",
            "url": note.link or "/notifications",
            "tag": str(note.id),
            "severity": note.severity,
        }
        urgency = "high" if note.severity == "critical" else "normal"
        results = [await self._deliver(d, payload, urgency=urgency) for d in devices]
        await self.session.commit()
        sent = sum(1 for r in results if r is PushResult.SENT)
        if sent == 0 and any(r is PushResult.RETRY for r in results):
            # Nothing got through and it might next time: let the queue try again.
            raise ServiceUnavailableError("The push service is not answering.", code="PUSH_RETRY")
        return sent

    async def _deliver(
        self, device: PushSubscription, payload: dict[str, str], *, urgency: str = "normal"
    ) -> PushResult:
        sub_id = device.id
        result = await send_push(
            self.settings,
            Device(endpoint=device.endpoint, p256dh=device.p256dh, auth=device.auth),
            payload,
            urgency=urgency,
        )
        if result is PushResult.SENT:
            await self.devices.sent(sub_id)
        elif result is PushResult.GONE or await self.devices.failed(sub_id) >= GIVE_UP_AFTER:
            await self.devices.forget(sub_id)
        return result
