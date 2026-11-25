"""How much email we may send: a rolling 24-hour allowance, and pacing per second.

Gmail refuses mail past about 500 a day, and a provider may cap the rate. Without a limit here a
big send would run into that wall and fail in the middle. With one, the excess waits (in the queue,
not lost) until there is room, and a share of the allowance is always kept back for tickets and
refunds so a newsletter can never use it all.

The count lives in Redis, so every worker process shares it. If Redis is down the limit is not
enforced rather than blocking mail: a mail provider that says no is a safer failure than silence.
"""

from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

BUCKET = 3600  # the 24 hours are counted an hour at a time
WINDOW = 24


class EmailDeferred(Exception):  # noqa: N818  (not an error: "not yet")
    """The allowance is used up. Try again at `until`; nothing is wrong."""

    def __init__(self, until: datetime, reason: str) -> None:
        super().__init__(reason)
        self.until = until
        self.reason = reason


class EmailBudget:
    def __init__(
        self,
        redis: Any,
        *,
        daily_limit: int,
        bulk_share: float,
        per_second: float,
        prefix: str = "email",
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.redis = redis
        self.daily_limit = daily_limit
        self.bulk_share = min(max(bulk_share, 0.0), 1.0)
        self.per_second = per_second
        self.prefix = prefix
        self.clock = clock
        self.sleep = sleep

    # ----------------------------------------------------------------- keys ---

    def _starts(self, now: float) -> list[int]:
        """Start of each hour in the window, oldest first, ending with the current hour."""
        current = int(now // BUCKET) * BUCKET
        return [current - (WINDOW - 1 - i) * BUCKET for i in range(WINDOW)]

    def _key(self, start: int) -> str:
        return f"{self.prefix}:h:{start}"

    async def _counts(self, starts: list[int]) -> list[int]:
        values = await self.redis.mget([self._key(s) for s in starts])
        return [int(v or 0) for v in values]

    async def used(self) -> int:
        """Emails counted in the last 24 hours."""
        return sum(await self._counts(self._starts(self.clock())))

    def cap(self, *, bulk: bool) -> int:
        if self.daily_limit <= 0:
            return 0
        return max(1, int(self.daily_limit * self.bulk_share)) if bulk else self.daily_limit

    # -------------------------------------------------------------- acquire ---

    async def acquire(self, *, bulk: bool) -> str | None:
        """Take one email's worth of allowance, or raise `EmailDeferred`. Returns a receipt."""
        receipt: str | None = None
        if self.daily_limit > 0:
            now = self.clock()
            starts = self._starts(now)
            current = self._key(starts[-1])
            # Count first, then look: two workers cannot both slip under the same last slot.
            await self.redis.incr(current)
            await self.redis.expire(current, (WINDOW + 1) * BUCKET)
            counts = await self._counts(starts)
            cap = self.cap(bulk=bulk)
            if sum(counts) > cap:
                await self.redis.decr(current)
                raise EmailDeferred(*self._when_free(starts, counts, cap, now, bulk))
            receipt = current
        await self._pace()
        return receipt

    def _when_free(
        self, starts: list[int], counts: list[int], cap: int, now: float, bulk: bool
    ) -> tuple[datetime, str]:
        # The count we compare against includes our own attempt, which was taken back.
        running = sum(counts) - 1
        free_at = starts[0] + WINDOW * BUCKET
        for start, count in zip(starts, counts, strict=True):
            running -= count
            if running < cap:
                free_at = start + WINDOW * BUCKET
                break
        free_at = max(free_at, int(now) + 60) + 30
        who = "Bulk email" if bulk else "Email"
        reason = f"{who} allowance used up ({cap} per 24 hours). Waiting for room."
        return datetime.fromtimestamp(free_at, UTC), reason

    async def _pace(self) -> None:
        if self.per_second <= 0:
            return
        limit = max(1, math.ceil(self.per_second))
        for _ in range(8):
            now = self.clock()
            key = f"{self.prefix}:s:{int(now)}"
            count = await self.redis.incr(key)
            await self.redis.expire(key, 5)
            if count <= limit:
                return
            await self.sleep(int(now) + 1 - now + 0.01)  # wait for the next second

    async def release(self, receipt: str | None) -> None:
        """Give back the allowance for an email that was not sent after all."""
        if receipt is not None:
            try:
                await self.redis.decr(receipt)
            except Exception:
                logger.warning("email_budget_release_failed")
