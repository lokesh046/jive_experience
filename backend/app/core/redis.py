"""Redis client lifecycle.

Redis is used for caching, rate limiting and (from Phase 6) as the broker for
background workers. It is deliberately **never** the source of truth for ticket
inventory — that is PostgreSQL's job.
"""

from __future__ import annotations

import redis.asyncio as aioredis
import structlog

from app.core.config import Settings

logger = structlog.get_logger(__name__)

_client: aioredis.Redis | None = None


def create_redis(settings: Settings) -> aioredis.Redis:
    """Build the process-wide Redis client."""
    global _client
    _client = aioredis.from_url(
        settings.redis_url,
        encoding="utf-8",
        decode_responses=True,
        health_check_interval=30,
        socket_connect_timeout=5,
        socket_timeout=5,
        retry_on_timeout=True,
    )
    return _client


def get_redis() -> aioredis.Redis:
    """Return the initialised client (raises if the app lifespan has not run)."""
    if _client is None:  # pragma: no cover - programming error
        raise RuntimeError("Redis client not initialised; call create_redis() first.")
    return _client


async def close_redis() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


async def redis_healthy() -> bool:
    try:
        return bool(await get_redis().ping())
    except Exception as exc:
        logger.warning("redis_health_check_failed", error=str(exc))
        return False
