"""Sending one push to the phone app through Expo's push service.

Expo hands the message on to Apple or Google. Like `webpush`, this holds no rules: it posts and
says what happened, so the caller can forget a device that has gone away.
"""

from __future__ import annotations

from typing import Any

import httpx
import structlog

from app.core.webpush import PushResult

logger = structlog.get_logger(__name__)

EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"


async def send_expo(
    token: str,
    payload: dict[str, Any],
    *,
    urgency: str = "normal",
    client: httpx.AsyncClient | None = None,
    url: str = EXPO_PUSH_URL,
) -> PushResult:
    message = {
        "to": token,
        "title": payload.get("title", ""),
        "body": payload.get("body", ""),
        "data": {"url": payload.get("url", "/notifications"), "id": payload.get("tag")},
        "sound": "default",
        "priority": "high" if urgency == "high" else "default",
    }
    try:
        if client is not None:
            response = await client.post(url, json=message, timeout=10)
        else:
            async with httpx.AsyncClient() as own:
                response = await own.post(url, json=message, timeout=10)
    except httpx.HTTPError:
        return PushResult.RETRY
    if response.status_code == 429 or response.status_code >= 500:
        return PushResult.RETRY
    if response.status_code >= 400:
        logger.warning("expo_push_refused", status=response.status_code)
        return PushResult.REFUSED
    try:
        data = response.json().get("data") or {}
    except ValueError:
        return PushResult.RETRY
    if isinstance(data, list):
        data = data[0] if data else {}
    if data.get("status") == "ok":
        return PushResult.SENT
    error = (data.get("details") or {}).get("error")
    if error == "DeviceNotRegistered":
        return PushResult.GONE
    logger.warning("expo_push_error", error=error)
    return PushResult.RETRY if error in ("MessageRateExceeded",) else PushResult.REFUSED
