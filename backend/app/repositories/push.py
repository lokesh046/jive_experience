from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any, cast

from sqlalchemy import CursorResult, delete, select, update
from sqlalchemy.dialects.postgresql import insert

from app.models.push_subscription import PushSubscription
from app.repositories.base import BaseRepository


class PushRepository(BaseRepository[PushSubscription]):
    model = PushSubscription

    async def upsert(
        self,
        *,
        user_id: uuid.UUID,
        endpoint: str,
        p256dh: str,
        auth: str,
        user_agent: str | None,
        provider: str = "webpush",
    ) -> None:
        """One row per device. A device signed in as someone else now belongs to this person."""
        statement = (
            insert(PushSubscription)
            .values(
                user_id=user_id,
                endpoint=endpoint,
                p256dh=p256dh,
                auth=auth,
                user_agent=user_agent,
                provider=provider,
            )
            .on_conflict_do_update(
                index_elements=["endpoint"],
                set_={
                    "user_id": user_id,
                    "p256dh": p256dh,
                    "auth": auth,
                    "user_agent": user_agent,
                    "provider": provider,
                    "failures": 0,
                },
            )
        )
        await self.session.execute(statement)

    async def for_user(self, user_id: uuid.UUID) -> Sequence[PushSubscription]:
        result = await self.session.execute(
            select(PushSubscription).where(PushSubscription.user_id == user_id)
        )
        return result.scalars().all()

    async def user_ids_with_devices(self, user_ids: Sequence[uuid.UUID]) -> set[uuid.UUID]:
        if not user_ids:
            return set()
        rows = await self.session.execute(
            select(PushSubscription.user_id)
            .where(PushSubscription.user_id.in_(user_ids))
            .distinct()
        )
        return set(rows.scalars().all())

    async def remove(self, *, user_id: uuid.UUID, endpoint: str) -> int:
        statement = delete(PushSubscription).where(
            PushSubscription.user_id == user_id, PushSubscription.endpoint == endpoint
        )
        result = cast("CursorResult[Any]", await self.session.execute(statement))
        return int(result.rowcount or 0)

    async def forget(self, subscription_id: uuid.UUID) -> None:
        await self.session.execute(
            delete(PushSubscription).where(PushSubscription.id == subscription_id)
        )

    async def sent(self, subscription_id: uuid.UUID) -> None:
        await self.session.execute(
            update(PushSubscription)
            .where(PushSubscription.id == subscription_id)
            .values(failures=0, last_sent_at=_now())
        )

    async def failed(self, subscription_id: uuid.UUID) -> int:
        """Count a failure; returns the running total."""
        result = await self.session.execute(
            update(PushSubscription)
            .where(PushSubscription.id == subscription_id)
            .values(failures=PushSubscription.failures + 1)
            .returning(PushSubscription.failures)
        )
        return int(result.scalar_one_or_none() or 0)


def _now() -> Any:
    from sqlalchemy import func

    return func.now()
