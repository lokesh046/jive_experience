"""Administrator-editable site settings. Today: the default refund policy."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.site_setting import DEFAULT_CANCELLATION_POLICY
from app.models.user import User
from app.repositories.catalogue import EventRepository
from app.repositories.site_setting import SiteSettingRepository
from app.schemas.policy import CancellationPolicy
from app.services.abandoned import SETTING_KEY as ABANDONED_KEY
from app.services.abandoned import abandoned_emails_enabled
from app.services.audit import AuditService
from app.services.cache import CatalogueCache


class SettingsService:
    def __init__(self, session: AsyncSession, cache: CatalogueCache) -> None:
        self.session = session
        self.cache = cache
        self.settings = SiteSettingRepository(session)
        self.events = EventRepository(session)
        self.audit = AuditService(session)

    async def default_policy(self) -> dict[str, Any] | None:
        return await self.settings.get(DEFAULT_CANCELLATION_POLICY)

    async def set_default_policy(self, policy: CancellationPolicy | None, *, actor: User) -> None:
        before = await self.default_policy()
        if policy is None or not policy.tiers:
            await self.settings.delete(DEFAULT_CANCELLATION_POLICY)
            after: dict[str, Any] | None = None
        else:
            after = policy.model_dump()
            await self.settings.put(DEFAULT_CANCELLATION_POLICY, after, updated_by=actor.id)
        await self.audit.record(
            "settings.cancellation_policy_changed",
            entity_type="site_setting",
            actor=actor,
            before={"policy": before},
            after={"policy": after},
        )
        await self.session.commit()
        # Every event page that shows the default policy must be rebuilt.
        slugs = list(await self.events.public_slugs())
        await self.cache.invalidate_details(slugs)

    async def abandoned_emails(self) -> bool:
        return await abandoned_emails_enabled(self.session)

    async def set_abandoned_emails(self, enabled: bool, *, actor: User) -> None:
        before = await self.abandoned_emails()
        await self.settings.put(ABANDONED_KEY, {"enabled": enabled}, updated_by=actor.id)
        await self.audit.record(
            "settings.abandoned_emails_changed",
            entity_type="site_setting",
            actor=actor,
            before={"enabled": before},
            after={"enabled": enabled},
        )
        await self.session.commit()
