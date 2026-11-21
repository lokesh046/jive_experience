"""Generic repository.

Every module needs the same handful of data-access operations. Writing them
once here means a module's own repository only declares its model and the
queries that are genuinely specific to it:

    class EventRepository(BaseRepository[Event]):
        model = Event

        async def published_in_city(self, city: str) -> Sequence[Event]:
            return await self.list(Event.status == EventStatus.PUBLISHED,
                                   Event.city == city)

Repositories hold queries and nothing else. Business rules live in the service
layer, and the service — not the repository — decides when to commit.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import ColumnExpressionArgument, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import UnaryExpression

from app.core.errors import NotFoundError
from app.core.pagination import PageParams
from app.models.base import Base

type Condition = ColumnExpressionArgument[bool]
type OrderBy = UnaryExpression[Any]


class BaseRepository[ModelT: Base]:
    """Read/write helpers shared by all modules."""

    model: type[ModelT]

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ------------------------------------------------------------ reads ----

    async def get(self, entity_id: uuid.UUID) -> ModelT | None:
        """Fetch by primary key, or None."""
        return await self.session.get(self.model, entity_id)

    async def get_or_fail(self, entity_id: uuid.UUID) -> ModelT:
        """Fetch by primary key, or raise the standard 404."""
        entity = await self.get(entity_id)
        if entity is None:
            raise NotFoundError(
                f"{self.model.__name__} not found.",
                details={"id": str(entity_id)},
            )
        return entity

    async def find_one(self, *where: Condition) -> ModelT | None:
        """First row matching the conditions, or None."""
        result = await self.session.execute(select(self.model).where(*where).limit(1))
        return result.scalar_one_or_none()

    async def exists(self, *where: Condition) -> bool:
        """Whether any row matches — never loads the row itself."""
        stmt = select(select(1).select_from(self.model).where(*where).exists())
        return bool(await self.session.scalar(stmt))

    async def count(self, *where: Condition) -> int:
        stmt = select(func.count()).select_from(self.model).where(*where)
        return int(await self.session.scalar(stmt) or 0)

    async def list(
        self,
        *where: Condition,
        order_by: Sequence[OrderBy] | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> Sequence[ModelT]:
        stmt = select(self.model).where(*where)
        if order_by:
            stmt = stmt.order_by(*order_by)
        if offset:
            stmt = stmt.offset(offset)
        if limit:
            stmt = stmt.limit(limit)
        return (await self.session.execute(stmt)).scalars().all()

    async def paginate(
        self,
        params: PageParams,
        *where: Condition,
        order_by: Sequence[OrderBy] | None = None,
    ) -> tuple[Sequence[ModelT], int]:
        """One page of rows plus the total matching count.

        Two queries rather than a windowed count: the count runs without the
        ORDER BY and without materialising the rows, which is what keeps admin
        tables fast as the booking table grows.

        The caller converts the rows to schemas and wraps them with
        `Page.build(...)`.
        """
        rows = await self.list(*where, order_by=order_by, limit=params.limit, offset=params.offset)
        total = await self.count(*where)
        return rows, total

    # ----------------------------------------------------------- writes ----

    def add(self, entity: ModelT) -> ModelT:
        """Stage a new row. The service commits."""
        self.session.add(entity)
        return entity

    async def delete(self, entity: ModelT) -> None:
        """Stage a delete. The service commits."""
        await self.session.delete(entity)

    async def flush(self) -> None:
        """Send pending changes so server defaults (ids, timestamps) are
        populated, without ending the transaction."""
        await self.session.flush()
