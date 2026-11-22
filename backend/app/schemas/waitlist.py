from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, EmailStr, Field

from app.core.pagination import Page
from app.models.waitlist import WaitlistStatus


class WaitlistJoin(BaseModel):
    email: EmailStr
    quantity: Annotated[int, Field(default=1, ge=1, le=4)] = 1
    # A particular ticket type, or null for any.
    ticket_category_id: uuid.UUID | None = None
    # A field real people never see; a bot that fills it is quietly ignored.
    website: Annotated[str, Field(default="", max_length=200)] = ""


class WaitlistLeave(BaseModel):
    token: Annotated[str, Field(min_length=20, max_length=64)]


class WaitlistRowOut(BaseModel):
    email: str
    quantity: int
    ticket_type: str | None = None
    status: WaitlistStatus
    created_at: datetime
    notified_at: datetime | None = None


class WaitlistPage(Page[WaitlistRowOut]):
    waiting: int = 0
    notified: int = 0
