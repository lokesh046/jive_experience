from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import func, select

from app.models.archive_item import ArchiveItem
from app.repositories.base import BaseRepository


class ArchiveRepository(BaseRepository[ArchiveItem]):
    model = ArchiveItem

    async def all_in_order(self) -> Sequence[ArchiveItem]:
        result = await self.session.execute(
            select(ArchiveItem).order_by(ArchiveItem.sort_order, ArchiveItem.created_at)
        )
        return result.scalars().all()

    async def visible_on_home(self, limit: int) -> Sequence[ArchiveItem]:
        result = await self.session.execute(
            select(ArchiveItem)
            .where(ArchiveItem.show_on_home.is_(True))
            .order_by(ArchiveItem.sort_order, ArchiveItem.created_at)
            .limit(limit)
        )
        return result.scalars().all()

    async def next_position(self) -> int:
        top = await self.session.scalar(select(func.max(ArchiveItem.sort_order)))
        return 0 if top is None else int(top) + 1
