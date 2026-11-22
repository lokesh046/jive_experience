"""Public forms (enquiry, newsletter) and the admin views of what came in."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, date, datetime
from typing import Annotated

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.core.pagination import Page
from app.models.lead import EnquiryStatus

PHONE = re.compile(r"^[0-9+()\-\s]{6,30}$")


class EnquiryCreate(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=120)]
    email: EmailStr
    phone: Annotated[str | None, Field(default=None, max_length=30)] = None
    event_date: date | None = None
    guests: Annotated[int | None, Field(default=None, ge=1, le=5000)] = None
    message: Annotated[str, Field(min_length=10, max_length=2000)]
    # A field real people never see. A bot that fills it is quietly ignored.
    website: Annotated[str, Field(default="", max_length=200)] = ""

    @field_validator("name", "message", "phone", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        return (value.strip() or None) if isinstance(value, str) else value

    @field_validator("phone")
    @classmethod
    def _phone(cls, value: str | None) -> str | None:
        if value is not None and not PHONE.match(value):
            raise ValueError("Enter a phone number using digits, spaces, + or -.")
        return value

    @field_validator("event_date")
    @classmethod
    def _not_past(cls, value: date | None) -> date | None:
        if value is not None and value < datetime.now(UTC).date():
            raise ValueError("Choose a date that has not passed.")
        return value


class SubscribeRequest(BaseModel):
    email: EmailStr
    website: Annotated[str, Field(default="", max_length=200)] = ""


class UnsubscribeRequest(BaseModel):
    token: Annotated[str, Field(min_length=20, max_length=64)]


class Received(BaseModel):
    """The same answer whether or not anything was stored, so a form reveals nothing."""

    ok: bool = True


class EnquiryOut(BaseModel):
    id: uuid.UUID
    name: str
    email: str
    phone: str | None = None
    event_date: date | None = None
    guests: int | None = None
    message: str
    status: EnquiryStatus
    admin_note: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class EnquiryUpdate(BaseModel):
    status: EnquiryStatus | None = None
    admin_note: Annotated[str | None, Field(default=None, max_length=2000)] = None


class SubscriberOut(BaseModel):
    email: str
    subscribed: bool
    created_at: datetime
    unsubscribed_at: datetime | None = None

    model_config = {"from_attributes": True}


class EnquiryPage(Page[EnquiryOut]):
    counts: dict[str, int] = Field(default_factory=dict)


class SubscriberPage(Page[SubscriberOut]):
    active: int = 0
