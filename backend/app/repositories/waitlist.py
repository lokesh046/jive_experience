from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import func, select

from app.core.pagination import PageParams
from app.models.event import TicketCategory
from app.models.waitlist import WaitlistEntry, WaitlistStatus
from app.repositories.base import BaseRepository


class WaitlistRepository(BaseRepository[WaitlistEntry]):
    model = WaitlistEntry

    async def for_person(self, event_id: uuid.UUID, email: str) -> WaitlistEntry | None:
        return await self.find_one(
            WaitlistEntry.event_id == event_id, WaitlistEntry.email == email.lower()
        )

    async def by_token(self, token: str) -> WaitlistEntry | None:
        return await self.find_one(WaitlistEntry.leave_token == token)

    async def events_with_waiting(self) -> Sequence[uuid.UUID]:
        statement = (
            select(WaitlistEntry.event_id)
            .where(WaitlistEntry.status == WaitlistStatus.WAITING)
            .distinct()
        )
        return (await self.session.execute(statement)).scalars().all()

    async def waiting_in_order(self, event_id: uuid.UUID) -> Sequence[WaitlistEntry]:
        return await self.list(
            WaitlistEntry.event_id == event_id,
            WaitlistEntry.status == WaitlistStatus.WAITING,
            order_by=[WaitlistEntry.created_at.asc()],
        )

    async def recently_notified(
        self, event_id: uuid.UUID, since: datetime
    ) -> Sequence[WaitlistEntry]:
        """People already told, who may still be on their way to buy."""
        return await self.list(
            WaitlistEntry.event_id == event_id,
            WaitlistEntry.status == WaitlistStatus.NOTIFIED,
            WaitlistEntry.notified_at >= since,
        )

    async def admin_page(
        self, event_id: uuid.UUID, params: PageParams
    ) -> tuple[list[tuple[Any, ...]], int]:
        base = (
            select(
                WaitlistEntry.email,
                WaitlistEntry.quantity,
                TicketCategory.name,
                WaitlistEntry.status,
                WaitlistEntry.created_at,
                WaitlistEntry.notified_at,
            )
            .outerjoin(TicketCategory, TicketCategory.id == WaitlistEntry.ticket_category_id)
            .where(WaitlistEntry.event_id == event_id, WaitlistEntry.status != WaitlistStatus.LEFT)
        )
        total = (
            await self.session.execute(
                select(func.count()).select_from(
                    select(WaitlistEntry.id)
                    .where(
                        WaitlistEntry.event_id == event_id,
                        WaitlistEntry.status != WaitlistStatus.LEFT,
                    )
                    .subquery()
                )
            )
        ).scalar_one()
        rows = (
            await self.session.execute(
                base.order_by(WaitlistEntry.created_at.asc())
                .offset(params.offset)
                .limit(params.limit)
            )
        ).all()
        return [tuple(r) for r in rows], int(total)

    async def counts(self, event_id: uuid.UUID) -> dict[str, int]:
        grouped = (
            select(WaitlistEntry.status, func.count())
            .where(WaitlistEntry.event_id == event_id)
            .group_by(WaitlistEntry.status)
        )
        return {str(r[0].value): int(r[1]) for r in (await self.session.execute(grouped)).all()}
