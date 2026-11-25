"""Sending one Web Push message. Kept free of rules: it encrypts, signs and posts, then says what
happened, so the caller can decide what to do about a device that has gone away.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import structlog
from pywebpush import WebPushException, webpush

from app.core.config import Settings

logger = structlog.get_logger(__name__)


class PushResult(StrEnum):
    SENT = "SENT"
    GONE = "GONE"  # the browser says this device no longer exists: forget it
    RETRY = "RETRY"  # the push service is busy or unreachable: try again later
    REFUSED = "REFUSED"  # a clear no that will not change (bad key, too large, forbidden)


@dataclass(frozen=True, slots=True)
class Device:
    endpoint: str
    p256dh: str
    auth: str


def _send_blocking(settings: Settings, device: Device, body: str, *, ttl: int, urgency: str) -> int:
    assert settings.vapid_private_key is not None
    response = webpush(
        subscription_info={
            "endpoint": device.endpoint,
            "keys": {"p256dh": device.p256dh, "auth": device.auth},
        },
        data=body,
        vapid_private_key=settings.vapid_private_key.get_secret_value(),
        vapid_claims={"sub": settings.vapid_subject},
        ttl=ttl,
        headers={"Urgency": urgency},
        timeout=10,
    )
    return int(response.status_code) if response is not None else 201


async def send_push(
    settings: Settings,
    device: Device,
    payload: dict[str, Any],
    *,
    ttl: int = 86400,
    urgency: str = "normal",
) -> PushResult:
    if not settings.push_configured:
        return PushResult.REFUSED
    body = json.dumps(payload, separators=(",", ":"))
    try:
        await asyncio.to_thread(_send_blocking, settings, device, body, ttl=ttl, urgency=urgency)
        return PushResult.SENT
    except WebPushException as exc:
        status = getattr(exc.response, "status_code", None)
        if status in (404, 410):
            return PushResult.GONE
        if status is None or status == 429 or status >= 500:
            logger.warning("push_retryable", status=status)
            return PushResult.RETRY
        logger.warning("push_refused", status=status)
        return PushResult.REFUSED
    except OSError:
        return PushResult.RETRY
