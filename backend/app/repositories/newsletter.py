from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any, cast

from sqlalchemy import CursorResult, func, select, update

from app.models.fulfilment import OutboxMessage, OutboxStatus
from app.models.lead import NewsletterSubscriber
from app.models.newsletter_campaign import CampaignStatus, NewsletterCampaign
from app.repositories.base import BaseRepository

TOPIC = "newsletter.send"


class CampaignRepository(BaseRepository[NewsletterCampaign]):
    model = NewsletterCampaign

    async def newest(self, limit: int = 50) -> Sequence[NewsletterCampaign]:
        result = await self.session.execute(
            select(NewsletterCampaign).order_by(NewsletterCampaign.created_at.desc()).limit(limit)
        )
        return result.scalars().all()

    async def mark_sent(self, campaign_id: uuid.UUID, *, recipients: int) -> bool:
        """Move a draft to sent, once. The guard makes a double click send one issue, not two."""
        statement = (
            update(NewsletterCampaign)
            .where(
                NewsletterCampaign.id == campaign_id,
                NewsletterCampaign.status == CampaignStatus.DRAFT.value,
            )
            .values(status=CampaignStatus.SENT.value, sent_at=func.now(), recipients=recipients)
        )
        result = cast("CursorResult[Any]", await self.session.execute(statement))
        return (result.rowcount or 0) == 1

    async def count_delivered(self, campaign_id: uuid.UUID) -> None:
        await self.session.execute(
            update(NewsletterCampaign)
            .where(NewsletterCampaign.id == campaign_id)
            .values(delivered=NewsletterCampaign.delivered + 1)
        )

    async def progress(self, campaign_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, tuple[int, int]]:
        """(still to send, gave up) per campaign, from the queue."""
        if not campaign_ids:
            return {}
        key = OutboxMessage.payload["campaign_id"].astext
        rows = (
            await self.session.execute(
                select(key, OutboxMessage.status, func.count())
                .where(OutboxMessage.topic == TOPIC, key.in_([str(i) for i in campaign_ids]))
                .group_by(key, OutboxMessage.status)
            )
        ).all()
        out: dict[uuid.UUID, list[int]] = {}
        for cid, status, n in rows:
            pair = out.setdefault(uuid.UUID(cid), [0, 0])
            if status in (OutboxStatus.PENDING, OutboxStatus.PROCESSING):
                pair[0] += int(n)
            elif status is OutboxStatus.FAILED:
                pair[1] += int(n)
        return {k: (v[0], v[1]) for k, v in out.items()}

    async def active_subscribers(self) -> Sequence[tuple[uuid.UUID, str]]:
        rows = (
            await self.session.execute(
                select(NewsletterSubscriber.id, NewsletterSubscriber.email)
                .where(NewsletterSubscriber.subscribed.is_(True))
                .order_by(NewsletterSubscriber.created_at)
            )
        ).all()
        return [(r[0], r[1]) for r in rows]
