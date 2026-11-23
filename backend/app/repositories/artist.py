from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import func, select

from app.models.artist import Artist
from app.repositories.base import BaseRepository


class ArtistRepository(BaseRepository[Artist]):
    model = Artist

    async def all_in_order(self) -> Sequence[Artist]:
        result = await self.session.execute(
            select(Artist).order_by(Artist.sort_order, Artist.created_at)
        )
        return result.scalars().all()

    async def visible_on_home(self, limit: int) -> Sequence[Artist]:
        result = await self.session.execute(
            select(Artist)
            .where(Artist.show_on_home.is_(True))
            .order_by(Artist.sort_order, Artist.created_at)
            .limit(limit)
        )
        return result.scalars().all()

    async def next_position(self) -> int:
        top = await self.session.scalar(select(func.max(Artist.sort_order)))
        return 0 if top is None else int(top) + 1
