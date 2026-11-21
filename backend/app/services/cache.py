"""Redis response cache for the public catalogue.

Why this exists: during a ticket release the overwhelming majority of traffic
is people loading the event page and polling availability — roughly a hundred
reads for every sale. Serving those from Redis keeps PostgreSQL free for the
work that actually has to be correct.

Two rules, both deliberate:

* **Short TTLs.** Seconds, not minutes. Stale availability is tolerable
  because the authoritative check happens inside the reservation transaction;
  stale *prices* are not, hence the short window and explicit invalidation.
* **Never fail the request.** Every operation degrades to a PostgreSQL read if
  Redis is unavailable. A cache outage must not take the public site down.
"""

from __future__ import annotations

import json
from typing import Any

import structlog
from redis.asyncio import Redis

logger = structlog.get_logger(__name__)

NAMESPACE = "cache:v1"

EVENT_LIST_TTL = 60
EVENT_DETAIL_TTL = 120
AVAILABILITY_TTL = 3
VENUE_CITIES_TTL = 300


class CatalogueCache:
    """Cache keys and invalidation for the public catalogue."""

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    # ------------------------------------------------------------ keys ----

    @staticmethod
    def list_key(fingerprint: str) -> str:
        return f"{NAMESPACE}:events:list:{fingerprint}"

    @staticmethod
    def detail_key(slug: str) -> str:
        return f"{NAMESPACE}:events:detail:{slug}"

    @staticmethod
    def availability_key(event_id: str) -> str:
        return f"{NAMESPACE}:events:availability:{event_id}"

    @staticmethod
    def cities_key() -> str:
        return f"{NAMESPACE}:venues:cities"

    # ------------------------------------------------------------ io ------

    async def get_json(self, key: str) -> Any | None:
        try:
            raw = await self._redis.get(key)
        except Exception as exc:
            logger.warning("cache_read_failed", key=key, error=str(exc))
            return None
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            # A corrupt entry is a cache miss, not an error.
            logger.warning("cache_entry_corrupt", key=key)
            return None

    async def set_json(self, key: str, value: Any, *, ttl: int) -> None:
        try:
            await self._redis.set(key, json.dumps(value, default=str), ex=ttl)
        except Exception as exc:
            logger.warning("cache_write_failed", key=key, error=str(exc))

    # ---------------------------------------------------- invalidation ----

    async def invalidate_event(self, *, slug: str | None, event_id: str | None) -> None:
        """Drop everything derived from one event.

        Called **after** the admin transaction commits — invalidating before
        the commit would let a concurrent read repopulate the cache with the
        old row.
        """
        keys = []
        if slug:
            keys.append(self.detail_key(slug))
        if event_id:
            keys.append(self.availability_key(event_id))
        if keys:
            await self._delete(keys)
        await self.invalidate_lists()

    async def invalidate_lists(self) -> None:
        """Drop every cached list page.

        Listings are filtered and paginated, so one event change can affect an
        unbounded number of entries. SCAN rather than KEYS: KEYS blocks Redis
        for the length of the scan, which during a drop is exactly when it
        must not.
        """
        pattern = f"{NAMESPACE}:events:list:*"
        try:
            batch: list[str] = []
            async for key in self._redis.scan_iter(match=pattern, count=200):
                batch.append(key)
                if len(batch) >= 200:
                    await self._redis.delete(*batch)
                    batch.clear()
            if batch:
                await self._redis.delete(*batch)
        except Exception as exc:
            logger.warning("cache_invalidate_failed", pattern=pattern, error=str(exc))

    async def invalidate_cities(self) -> None:
        await self._delete([self.cities_key()])

    async def _delete(self, keys: list[str]) -> None:
        try:
            await self._redis.delete(*keys)
        except Exception as exc:
            logger.warning("cache_delete_failed", error=str(exc))
