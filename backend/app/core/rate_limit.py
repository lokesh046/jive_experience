"""Redis-backed rate limiting.

A fixed-window counter (INCR + EXPIRE) is used: it is one round trip, is exact
enough for abuse control, and needs no background sweeping. Burst smoothing at
the window edge is acceptable here — the sensitive flows (OAuth callback,
admin login) are additionally fail-closed.

`fail_open` controls behaviour when Redis itself is unreachable:

* public/browse endpoints: fail open — a cache outage must not take the site
  down;
* authentication endpoints: fail **closed** — losing the limiter must not
  silently open a credential-stuffing window.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Final

import structlog
from fastapi import Request, Response

from app.core.config import Settings, get_settings
from app.core.errors import RateLimitedError, ServiceUnavailableError
from app.core.redis import get_redis

logger = structlog.get_logger(__name__)

KEY_PREFIX: Final = "rl"

type IdentifierFn = Callable[[Request], str]


def client_ip(request: Request) -> str:
    """Caller IP.

    Behind nginx/Caddy the API runs with uvicorn `--proxy-headers`, so
    `request.client.host` is already the real client address. Reading
    X-Forwarded-For directly here would let any caller spoof their identity.
    """
    return request.client.host if request.client else "unknown"


class RateLimiter:
    """FastAPI dependency enforcing `times` requests per `seconds` window."""

    def __init__(
        self,
        *,
        times: int,
        seconds: int,
        scope: str,
        identifier: IdentifierFn = client_ip,
        fail_open: bool = True,
    ) -> None:
        self.times = times
        self.seconds = seconds
        self.scope = scope
        self.identifier = identifier
        self.fail_open = fail_open

    async def __call__(self, request: Request, response: Response) -> None:
        settings: Settings = getattr(request.app.state, "settings", None) or get_settings()
        if not settings.rate_limit_enabled:
            return

        ident = self.identifier(request)

        window = _current_window(self.seconds)
        key = f"{KEY_PREFIX}:{self.scope}:{ident}:{window}"

        try:
            async with get_redis().pipeline(transaction=True) as pipe:
                pipe.incr(key)
                pipe.expire(key, self.seconds)
                count, _ = await pipe.execute()
        except Exception as exc:
            logger.warning("rate_limiter_unavailable", scope=self.scope, error=str(exc))
            if self.fail_open:
                return
            raise ServiceUnavailableError(
                "Rate limiting is temporarily unavailable; request rejected.",
                code="RATE_LIMITER_UNAVAILABLE",
            ) from exc

        remaining = max(self.times - int(count), 0)
        response.headers["X-RateLimit-Limit"] = str(self.times)
        response.headers["X-RateLimit-Remaining"] = str(remaining)

        if int(count) > self.times:
            retry_after = self.seconds
            logger.info("rate_limited", scope=self.scope, identifier=ident)
            raise RateLimitedError(
                f"Rate limit exceeded: {self.times} requests per {self.seconds}s.",
                details={"retry_after_seconds": retry_after},
            )


def _current_window(seconds: int) -> int:
    """Index of the current fixed window."""
    return int(time.time()) // seconds
