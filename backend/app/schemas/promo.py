"""Promo codes: what an admin creates, and what a customer's check returns."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.pagination import Page
from app.models.promo import PromoDiscountType
from app.schemas.booking import BookingItemRequest

CODE = re.compile(r"^[A-Z0-9][A-Z0-9_-]{2,31}$")


def normalise_code(value: str) -> str:
    return re.sub(r"\s+", "", value).upper()


class PromoCreate(BaseModel):
    code: Annotated[str, Field(min_length=3, max_length=32)]
    description: Annotated[str | None, Field(default=None, max_length=200)] = None
    discount_type: PromoDiscountType
    percent_off: Annotated[int | None, Field(default=None, ge=1, le=100)] = None
    amount_off_paise: Annotated[int | None, Field(default=None, ge=1)] = None
    event_id: uuid.UUID | None = None
    max_uses: Annotated[int | None, Field(default=None, ge=1)] = None
    max_uses_per_customer: Annotated[int | None, Field(default=1, ge=1)] = 1
    valid_from: datetime | None = None
    valid_until: datetime | None = None

    @field_validator("code")
    @classmethod
    def _code(cls, value: str) -> str:
        code = normalise_code(value)
        if not CODE.match(code):
            raise ValueError("Use 3 to 32 letters, numbers, dashes or underscores.")
        return code

    @model_validator(mode="after")
    def _check(self) -> PromoCreate:
        if self.discount_type is PromoDiscountType.PERCENT:
            if self.percent_off is None or self.amount_off_paise is not None:
                raise ValueError("A percentage code needs a percentage, and no fixed amount.")
        elif self.amount_off_paise is None or self.percent_off is not None:
            raise ValueError("A fixed-amount code needs an amount, and no percentage.")
        if self.valid_from and self.valid_until and self.valid_until <= self.valid_from:
            raise ValueError("The end must be after the start.")
        return self


class PromoUpdate(BaseModel):
    """Only what can change safely. The discount, scope and code are fixed once created."""

    description: Annotated[str | None, Field(default=None, max_length=200)] = None
    is_active: bool | None = None
    max_uses: Annotated[int | None, Field(default=None, ge=1)] = None
    max_uses_per_customer: Annotated[int | None, Field(default=None, ge=1)] = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None


class PromoOut(BaseModel):
    id: uuid.UUID
    code: str
    description: str | None = None
    discount_type: PromoDiscountType
    percent_off: int | None = None
    amount_off_paise: int | None = None
    event_id: uuid.UUID | None = None
    max_uses: int | None = None
    used_count: int
    max_uses_per_customer: int | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class PromoPage(Page[PromoOut]):
    pass


class PromoCheckRequest(BaseModel):
    event_slug: Annotated[str, Field(min_length=1, max_length=160)]
    code: Annotated[str, Field(min_length=1, max_length=40)]
    items: Annotated[list[BookingItemRequest], Field(min_length=1, max_length=10)]


class PromoCheckOut(BaseModel):
    """What the code would take off, worked out on the server."""

    code: str
    subtotal_paise: int
    discount_paise: int
    total_paise: int
    description: str | None = None
