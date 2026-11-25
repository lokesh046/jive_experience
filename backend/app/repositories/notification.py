from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any, cast

from sqlalchemy import CursorResult, delete, func, select, text, tuple_, update
from sqlalchemy.dialects.postgresql import insert

from app.models.notification import Notification, NotificationPreference
from app.models.user import User, UserRole, UserStatus
from app.repositories.base import BaseRepository


class NotificationRepository(BaseRepository[Notification]):
    model = Notification

    async def add_many(self, rows: Sequence[dict[str, Any]]) -> list[uuid.UUID]:
        """Insert, skipping any that repeat a person's dedup key. Returns the ids that were new."""
        created: list[uuid.UUID] = []
        for values in rows:
            statement = (
                insert(Notification)
                .values(**values)
                .on_conflict_do_nothing(
                    index_elements=["user_id", "dedup_key"],
                    index_where=text("dedup_key IS NOT NULL"),
                )
                .returning(Notification.id)
            )
            new_id = (await self.session.execute(statement)).scalar_one_or_none()
            if new_id is not None:
                created.append(new_id)
        return created

    async def feed(
        self,
        user_id: uuid.UUID,
        *,
        limit: int,
        before: tuple[datetime, uuid.UUID] | None,
        unread_only: bool,
    ) -> Sequence[Notification]:
        statement = select(Notification).where(Notification.user_id == user_id)
        if before is not None:
            # (created_at, id) together, so notifications made in one instant still page cleanly.
            statement = statement.where(
                tuple_(Notification.created_at, Notification.id) < tuple_(before[0], before[1])
            )
        if unread_only:
            statement = statement.where(Notification.read_at.is_(None))
        statement = statement.order_by(
            Notification.created_at.desc(), Notification.id.desc()
        ).limit(limit)
        return (await self.session.execute(statement)).scalars().all()

    async def unread_count(self, user_id: uuid.UUID) -> int:
        return await self.count(Notification.user_id == user_id, Notification.read_at.is_(None))

    async def mark_read(self, user_id: uuid.UUID, ids: Sequence[uuid.UUID] | None) -> int:
        statement = (
            update(Notification)
            .where(Notification.user_id == user_id, Notification.read_at.is_(None))
            .values(read_at=func.now())
        )
        if ids is not None:
            statement = statement.where(Notification.id.in_(ids))
        result = cast("CursorResult[Any]", await self.session.execute(statement))
        return int(result.rowcount or 0)

    async def prune(self, *, read_before: datetime, any_before: datetime) -> int:
        statement = delete(Notification).where(
            (Notification.created_at < any_before)
            | ((Notification.read_at.is_not(None)) & (Notification.created_at < read_before))
        )
        result = cast("CursorResult[Any]", await self.session.execute(statement))
        return int(result.rowcount or 0)

    async def active_admin_ids(self) -> list[uuid.UUID]:
        rows = await self.session.execute(
            select(User.id).where(User.role == UserRole.ADMIN, User.status == UserStatus.ACTIVE)
        )
        return list(rows.scalars().all())


class PreferenceRepository:
    def __init__(self, session: Any) -> None:
        self.session = session

    async def for_users(
        self, user_ids: Sequence[uuid.UUID]
    ) -> dict[tuple[uuid.UUID, str, str], bool]:
        if not user_ids:
            return {}
        rows = (
            await self.session.execute(
                select(NotificationPreference).where(NotificationPreference.user_id.in_(user_ids))
            )
        ).scalars()
        return {(p.user_id, p.category, p.channel): p.enabled for p in rows}

    async def put(self, user_id: uuid.UUID, category: str, channel: str, enabled: bool) -> None:
        statement = (
            insert(NotificationPreference)
            .values(user_id=user_id, category=category, channel=channel, enabled=enabled)
            .on_conflict_do_update(
                index_elements=["user_id", "category", "channel"], set_={"enabled": enabled}
            )
        )
        await self.session.execute(statement)
