"""Notification contracts."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field


class NotificationOut(BaseModel):
    id: uuid.UUID
    kind: str
    category: str
    severity: str
    title: str
    body: str | None = None
    link: str | None = None
    read: bool
    created_at: datetime


class FeedOut(BaseModel):
    items: list[NotificationOut]
    unread: int
    # Pass back as `before` to get the next, older page. Null when there is no more.
    next_before: str | None = None


class UnreadOut(BaseModel):
    unread: int


class MarkRead(BaseModel):
    ids: Annotated[list[uuid.UUID], Field(min_length=1, max_length=100)]


class PreferenceOut(BaseModel):
    category: str
    label: str
    description: str
    in_app: bool
    email: bool
    push: bool
    # Whether the email switch does anything for this group.
    email_choice: bool


class PreferenceUpdate(BaseModel):
    category: str
    in_app: bool | None = None
    email: bool | None = None
    push: bool | None = None


class PreferencesIn(BaseModel):
    changes: Annotated[list[PreferenceUpdate], Field(min_length=1, max_length=20)]


class PushKeyOut(BaseModel):
    configured: bool
    public_key: str | None = None


class PushKeys(BaseModel):
    p256dh: Annotated[str, Field(min_length=20, max_length=200)]
    auth: Annotated[str, Field(min_length=8, max_length=100)]


class PushSubscribeIn(BaseModel):
    """What a browser's `PushSubscription.toJSON()` gives."""

    endpoint: Annotated[str, Field(min_length=20, max_length=1024, pattern=r"^https://")]
    keys: PushKeys


class PhoneDeviceIn(BaseModel):
    """The phone app's Expo push token."""

    token: Annotated[
        str, Field(min_length=20, max_length=200, pattern=r"^(Exponent|Expo)PushToken\[[^\]]+\]$")
    ]
    platform: Annotated[str, Field(pattern=r"^(ios|android)$")]


class PushUnsubscribeIn(BaseModel):
    endpoint: Annotated[str, Field(min_length=20, max_length=1024)]


class PushDevicesOut(BaseModel):
    devices: int


class PushTestOut(BaseModel):
    sent: int
