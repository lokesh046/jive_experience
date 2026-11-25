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
    # Whether the email switch does anything for this group.
    email_choice: bool


class PreferenceUpdate(BaseModel):
    category: str
    in_app: bool | None = None
    email: bool | None = None


class PreferencesIn(BaseModel):
    changes: Annotated[list[PreferenceUpdate], Field(min_length=1, max_length=20)]
