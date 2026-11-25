"""Newsletter contracts."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field, field_validator, model_validator


def _clean(value: object) -> object:
    if isinstance(value, str):
        return value.strip() or None
    return value


class CampaignIn(BaseModel):
    subject: Annotated[str, Field(min_length=1, max_length=200)]
    body: Annotated[str, Field(min_length=1, max_length=10000)]
    event_id: uuid.UUID | None = None
    button_label: Annotated[str | None, Field(default=None, max_length=60)] = None
    button_url: Annotated[str | None, Field(default=None, max_length=500)] = None

    @field_validator("subject", "body", "button_label", "button_url", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        return _clean(value)

    @field_validator("button_url")
    @classmethod
    def _web(cls, value: str | None) -> str | None:
        if value is not None and not value.lower().startswith(("https://", "http://")):
            raise ValueError("The button link must be a web address.")
        return value

    @model_validator(mode="after")
    def _both_or_neither(self) -> CampaignIn:
        if bool(self.button_label) != bool(self.button_url):
            raise ValueError("A button needs both a label and a link.")
        return self


class CampaignOut(BaseModel):
    id: uuid.UUID
    subject: str
    body: str
    event_id: uuid.UUID | None = None
    button_label: str | None = None
    button_url: str | None = None
    status: str
    sent_at: datetime | None = None
    recipients: int
    delivered: int
    # Still to go out, and gave up after retries: both read from the queue.
    pending: int = 0
    failed: int = 0
    created_at: datetime

    model_config = {"from_attributes": True}


class CampaignSendOut(BaseModel):
    queued: int


class CampaignTestOut(BaseModel):
    sent_to: str
