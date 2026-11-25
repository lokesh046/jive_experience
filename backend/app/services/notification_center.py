"""One place that says "tell this person": the bell, and the alert email where they want one.

Every producer (the worker handlers, the sweeper, the services) calls `notify_*` instead of
writing its own message, so a person's switches are honoured the same way everywhere and the
same event never notifies them twice.

The caller owns the transaction: nothing here commits, so a notification exists if and only if
the thing it describes was saved.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import BusinessRuleError, NotFoundError
from app.core.notification_kinds import BY_KEY, CHANNELS, Category, categories_for
from app.models.fulfilment import StaffEventAssignment
from app.models.notification import Notification
from app.models.user import User
from app.repositories.notification import NotificationRepository, PreferenceRepository
from app.schemas.notification import PreferenceOut, PreferencesIn
from app.services.outbox import TOPIC_NOTIFICATION_EMAIL, OutboxService

logger = structlog.get_logger(__name__)

SEVERITIES = ("info", "warn", "critical")
READ_KEPT_DAYS = 60
ANY_KEPT_DAYS = 180


class NotificationCenter:
    def __init__(self, session: AsyncSession, outbox: OutboxService | None = None) -> None:
        self.session = session
        self.outbox = outbox or OutboxService(session)
        self.notifications = NotificationRepository(session)
        self.preferences = PreferenceRepository(session)

    # ------------------------------------------------------------ sending ---

    async def notify(
        self,
        users: Sequence[uuid.UUID],
        *,
        kind: str,
        category: str,
        title: str,
        body: str | None = None,
        link: str | None = None,
        severity: str = "info",
        dedup_key: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> int:
        """Tell each person once. Returns how many bell entries were created."""
        if category not in BY_KEY:
            raise ValueError(f"Unknown notification category: {category}")
        if severity not in SEVERITIES:
            raise ValueError(f"Unknown severity: {severity}")
        if link is not None and not link.startswith("/"):
            raise ValueError("A notification link must be a path on this site.")
        people = list(dict.fromkeys(users))
        if not people:
            return 0
        spec = BY_KEY[category]
        prefs = await self.preferences.for_users(people)

        def wants(user_id: uuid.UUID, channel: str) -> bool:
            default = spec.in_app_default if channel == "in_app" else spec.email_default
            return prefs.get((user_id, category, channel), default)

        rows = [
            {
                "user_id": user_id,
                "kind": kind,
                "category": category,
                "severity": severity,
                "title": title[:160],
                "body": body[:500] if body else None,
                "link": link,
                "dedup_key": dedup_key,
                "data": data,
            }
            for user_id in people
            if wants(user_id, "in_app")
        ]
        created = await self.notifications.add_many(rows)

        if spec.alert_email and created:
            emailed = {u for u in people if wants(u, "email")}
            owners = await self._owners(created)
            for notification_id, user_id in owners.items():
                if user_id in emailed:
                    await self.outbox.enqueue(
                        topic=TOPIC_NOTIFICATION_EMAIL,
                        payload={"notification_id": str(notification_id)},
                        dedup_key=f"{TOPIC_NOTIFICATION_EMAIL}:{notification_id}",
                    )
        return len(created)

    async def notify_admins(self, **kwargs: Any) -> int:
        return await self.notify(await self.notifications.active_admin_ids(), **kwargs)

    async def notify_event_staff(
        self, event_id: uuid.UUID, *, include_admins: bool = False, **kwargs: Any
    ) -> int:
        """The people working a night: assigned gate staff, and optionally every administrator."""
        rows = await self.session.execute(
            select(StaffEventAssignment.user_id).where(
                StaffEventAssignment.event_id == event_id,
                StaffEventAssignment.revoked_at.is_(None),
            )
        )
        people = list(rows.scalars().all())
        if include_admins:
            people += await self.notifications.active_admin_ids()
        return await self.notify(people, **kwargs)

    async def _owners(self, ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, uuid.UUID]:
        rows = await self.session.execute(
            select(Notification.id, Notification.user_id).where(Notification.id.in_(ids))
        )
        return {r[0]: r[1] for r in rows.all()}

    # ------------------------------------------------------------ reading ---

    async def feed(
        self,
        user: User,
        *,
        limit: int = 20,
        before: tuple[datetime, uuid.UUID] | None = None,
        unread_only: bool = False,
    ) -> tuple[list[Notification], int, str | None]:
        rows = list(
            await self.notifications.feed(
                user.id, limit=limit + 1, before=before, unread_only=unread_only
            )
        )
        more = len(rows) > limit
        rows = rows[:limit]
        cursor = f"{rows[-1].created_at.isoformat()}|{rows[-1].id}" if more and rows else None
        return rows, await self.notifications.unread_count(user.id), cursor

    async def unread_count(self, user: User) -> int:
        return await self.notifications.unread_count(user.id)

    async def mark_read(self, user: User, ids: Sequence[uuid.UUID] | None) -> int:
        count = await self.notifications.mark_read(user.id, ids)
        await self.session.commit()
        return count

    # -------------------------------------------------------- preferences ---

    async def preferences_for(self, user: User) -> list[PreferenceOut]:
        stored = await self.preferences.for_users([user.id])
        out = []
        for c in categories_for(user.role):
            out.append(
                PreferenceOut(
                    category=c.key,
                    label=c.label,
                    description=c.description,
                    in_app=stored.get((user.id, c.key, "in_app"), c.in_app_default),
                    email=stored.get((user.id, c.key, "email"), c.email_default),
                    email_choice=c.email_choice,
                )
            )
        return out

    async def set_preferences(self, user: User, payload: PreferencesIn) -> list[PreferenceOut]:
        allowed = {c.key: c for c in categories_for(user.role)}
        for change in payload.changes:
            spec: Category | None = allowed.get(change.category)
            if spec is None:
                raise NotFoundError(
                    "That group of notifications does not exist.", code="CATEGORY_NOT_FOUND"
                )
            if change.in_app is not None:
                await self.preferences.put(user.id, spec.key, "in_app", change.in_app)
            if change.email is not None:
                if not spec.email_choice:
                    raise BusinessRuleError(
                        "Email for this group cannot be changed.", code="EMAIL_NOT_OPTIONAL"
                    )
                await self.preferences.put(user.id, spec.key, "email", change.email)
        await self.session.commit()
        return await self.preferences_for(user)

    async def email_wanted(self, user_id: uuid.UUID, category: str) -> bool:
        """For emails sent elsewhere (reminders, waitlist): has this person left them on?"""
        spec = BY_KEY[category]
        stored = await self.preferences.for_users([user_id])
        return stored.get((user_id, category, "email"), spec.email_default)

    # ------------------------------------------------------- housekeeping ---

    async def prune(self, now: datetime | None = None) -> int:
        now = now or datetime.now(UTC)
        return await self.notifications.prune(
            read_before=now - timedelta(days=READ_KEPT_DAYS),
            any_before=now - timedelta(days=ANY_KEPT_DAYS),
        )


__all__ = ["CHANNELS", "NotificationCenter"]
