"""The archive: photos of past nights, shown on the homepage in an order the admin chooses."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import BusinessRuleError, NotFoundError
from app.models.archive_item import ArchiveItem
from app.models.user import User
from app.repositories.archive import ArchiveRepository
from app.schemas.archive import ArchiveIn, ArchiveOrder, ArchiveUpdate
from app.services.audit import AuditService

HOME_LIMIT = 6


class ArchiveService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.items = ArchiveRepository(session)
        self.audit = AuditService(session)

    async def list_all(self) -> Sequence[ArchiveItem]:
        return await self.items.all_in_order()

    async def for_home(self) -> Sequence[ArchiveItem]:
        return await self.items.visible_on_home(HOME_LIMIT)

    async def create(self, payload: ArchiveIn, *, actor: User) -> ArchiveItem:
        item = ArchiveItem(
            caption=payload.caption,
            photo_url=payload.photo_url,
            show_on_home=payload.show_on_home,
            sort_order=await self.items.next_position(),
        )
        self.items.add(item)
        await self.session.flush()
        await self.audit.record(
            "archive.created",
            entity_type="archive_item",
            entity_id=item.id,
            actor=actor,
            after={"caption": item.caption},
        )
        await self.session.commit()
        return item

    async def update(
        self, item_id: uuid.UUID, payload: ArchiveUpdate, *, actor: User
    ) -> ArchiveItem:
        item = await self._get(item_id)
        changes = payload.model_dump(exclude_unset=True)
        if "photo_url" in changes and not changes["photo_url"]:
            raise BusinessRuleError(
                "An archive photo needs a picture. Replace it, or remove the item.",
                code="ARCHIVE_PHOTO_REQUIRED",
            )
        for field, value in changes.items():
            setattr(item, field, value)
        await self.audit.record(
            "archive.updated",
            entity_type="archive_item",
            entity_id=item.id,
            actor=actor,
            after={k: v for k, v in changes.items() if k != "photo_url"},
        )
        await self.session.commit()
        return item

    async def delete(self, item_id: uuid.UUID, *, actor: User) -> None:
        item = await self._get(item_id)
        await self.audit.record(
            "archive.deleted",
            entity_type="archive_item",
            entity_id=item.id,
            actor=actor,
            before={"caption": item.caption},
        )
        await self.items.delete(item)
        await self.session.commit()

    async def reorder(self, payload: ArchiveOrder, *, actor: User) -> Sequence[ArchiveItem]:
        """Set the order from a full list of ids, so two admins cannot half-apply each other's."""
        current = {i.id: i for i in await self.items.all_in_order()}
        if len(set(payload.ids)) != len(payload.ids) or set(payload.ids) != set(current):
            raise BusinessRuleError(
                "The list is out of date. Reload and try again.", code="ARCHIVE_ORDER_STALE"
            )
        for position, item_id in enumerate(payload.ids):
            current[item_id].sort_order = position
        await self.audit.record(
            "archive.reordered", entity_type="archive_item", entity_id=None, actor=actor
        )
        await self.session.commit()
        return await self.items.all_in_order()

    async def _get(self, item_id: uuid.UUID) -> ArchiveItem:
        item = await self.items.get(item_id)
        if item is None:
            raise NotFoundError("Archive photo not found.", code="ARCHIVE_NOT_FOUND")
        return item
