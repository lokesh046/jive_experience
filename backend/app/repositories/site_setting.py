from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.site_setting import SiteSetting


class SiteSettingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, key: str) -> dict[str, Any] | None:
        row = (
            await self.session.execute(select(SiteSetting).where(SiteSetting.key == key))
        ).scalar_one_or_none()
        return row.value if row else None

    async def put(self, key: str, value: dict[str, Any], *, updated_by: uuid.UUID | None) -> None:
        row = (
            await self.session.execute(select(SiteSetting).where(SiteSetting.key == key))
        ).scalar_one_or_none()
        if row is None:
            self.session.add(SiteSetting(key=key, value=value, updated_by_id=updated_by))
        else:
            row.value = value
            row.updated_by_id = updated_by

    async def delete(self, key: str) -> None:
        row = (
            await self.session.execute(select(SiteSetting).where(SiteSetting.key == key))
        ).scalar_one_or_none()
        if row is not None:
            await self.session.delete(row)
