"""Notifications for whoever is signed in: customers, gate staff and administrators."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query

from app.core.errors import BusinessRuleError
from app.dependencies import CurrentUser, NotificationCenterDep
from app.models.notification import Notification
from app.schemas.notification import (
    FeedOut,
    MarkRead,
    NotificationOut,
    PreferenceOut,
    PreferencesIn,
    UnreadOut,
)

router = APIRouter(tags=["notifications"])


def _out(n: Notification) -> NotificationOut:
    return NotificationOut(
        id=n.id,
        kind=n.kind,
        category=n.category,
        severity=n.severity,
        title=n.title,
        body=n.body,
        link=n.link,
        read=n.read_at is not None,
        created_at=n.created_at,
    )


@router.get("", response_model=FeedOut, summary="My notifications, newest first")
async def feed(
    user: CurrentUser,
    service: NotificationCenterDep,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    before: Annotated[str | None, Query(max_length=80)] = None,
    unread_only: bool = False,
) -> FeedOut:
    cursor: tuple[datetime, uuid.UUID] | None = None
    if before:
        try:
            stamp, _, ident = before.partition("|")
            cursor = (datetime.fromisoformat(stamp), uuid.UUID(ident))
        except ValueError as exc:
            raise BusinessRuleError("That page marker is not valid.", code="BAD_CURSOR") from exc
    rows, unread, next_before = await service.feed(
        user, limit=limit, before=cursor, unread_only=unread_only
    )
    return FeedOut(items=[_out(n) for n in rows], unread=unread, next_before=next_before)


@router.get("/unread", response_model=UnreadOut, summary="How many I have not read")
async def unread(user: CurrentUser, service: NotificationCenterDep) -> UnreadOut:
    return UnreadOut(unread=await service.unread_count(user))


@router.post("/read", response_model=UnreadOut, summary="Mark some as read")
async def read(payload: MarkRead, user: CurrentUser, service: NotificationCenterDep) -> UnreadOut:
    await service.mark_read(user, payload.ids)
    return UnreadOut(unread=await service.unread_count(user))


@router.post("/read-all", response_model=UnreadOut, summary="Mark everything as read")
async def read_all(user: CurrentUser, service: NotificationCenterDep) -> UnreadOut:
    await service.mark_read(user, None)
    return UnreadOut(unread=0)


@router.get(
    "/preferences", response_model=list[PreferenceOut], summary="Which notifications I want"
)
async def get_preferences(user: CurrentUser, service: NotificationCenterDep) -> list[PreferenceOut]:
    return await service.preferences_for(user)


@router.put(
    "/preferences", response_model=list[PreferenceOut], summary="Change what I want to be told"
)
async def put_preferences(
    payload: PreferencesIn, user: CurrentUser, service: NotificationCenterDep
) -> list[PreferenceOut]:
    return await service.set_preferences(user, payload)
