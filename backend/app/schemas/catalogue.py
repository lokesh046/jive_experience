"""Venue, event and ticket-category contracts.

Public and admin shapes are separate. A customer must never see draft events,
internal counters or who created a record, so the public schema simply does
not have those fields rather than relying on a conditional.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Annotated, Any

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    Field,
    field_validator,
    model_validator,
)

from app.models.event import EventCategory, EventStatus

SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def slugify(value: str) -> str:
    """URL-safe slug. SEO-friendly event URLs are a stated requirement."""
    lowered = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return re.sub(r"-{2,}", "-", lowered)[:160]


# ------------------------------------------------------------------ venues ---


def _clean_list(value: object) -> object:
    """Trim each line and drop blanks, so an empty text box saves as an empty list."""
    if value is None:
        return None
    if isinstance(value, list):
        return [item.strip() for item in value if isinstance(item, str) and item.strip()]
    return value


def _at_most(limit: int, what: str) -> AfterValidator:
    def check(value: list[str] | None) -> list[str] | None:
        if value is not None and len(value) > limit:
            raise ValueError(f"At most {limit} {what}.")
        return value

    return AfterValidator(check)


VenueImages = Annotated[
    list[Annotated[str, Field(max_length=1024)]] | None,
    BeforeValidator(_clean_list),
    _at_most(8, "photos"),
]
VenueBenefits = Annotated[
    list[Annotated[str, Field(max_length=120)]] | None,
    BeforeValidator(_clean_list),
    _at_most(12, "benefits"),
]


class VenueCreate(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=200)]
    address_line1: Annotated[str, Field(min_length=1, max_length=200)]
    address_line2: Annotated[str | None, Field(default=None, max_length=200)] = None
    city: Annotated[str, Field(min_length=1, max_length=100)]
    state: Annotated[str | None, Field(default=None, max_length=100)] = None
    postal_code: Annotated[str | None, Field(default=None, max_length=20)] = None
    country_code: Annotated[str, Field(default="IN", min_length=2, max_length=2)] = "IN"
    latitude: Annotated[float | None, Field(default=None, ge=-90, le=90)] = None
    longitude: Annotated[float | None, Field(default=None, ge=-180, le=180)] = None
    seating_capacity: Annotated[int | None, Field(default=None, ge=0)] = None
    directions: str | None = None
    map_url: Annotated[str | None, Field(default=None, max_length=512)] = None
    description: Annotated[str | None, Field(default=None, max_length=4000)] = None
    image_urls: VenueImages = None
    benefits: VenueBenefits = None


class VenueUpdate(BaseModel):
    name: Annotated[str | None, Field(default=None, min_length=1, max_length=200)] = None
    address_line1: Annotated[str | None, Field(default=None, max_length=200)] = None
    address_line2: Annotated[str | None, Field(default=None, max_length=200)] = None
    city: Annotated[str | None, Field(default=None, min_length=1, max_length=100)] = None
    state: Annotated[str | None, Field(default=None, max_length=100)] = None
    postal_code: Annotated[str | None, Field(default=None, max_length=20)] = None
    seating_capacity: Annotated[int | None, Field(default=None, ge=0)] = None
    directions: str | None = None
    map_url: Annotated[str | None, Field(default=None, max_length=512)] = None
    description: Annotated[str | None, Field(default=None, max_length=4000)] = None
    image_urls: VenueImages = None
    benefits: VenueBenefits = None


class VenueOut(BaseModel):
    id: uuid.UUID
    name: str
    address_line1: str
    address_line2: str | None = None
    city: str
    state: str | None = None
    postal_code: str | None = None
    country_code: str
    latitude: float | None = None
    longitude: float | None = None
    map_url: str | None = None
    directions: str | None = None
    description: str | None = None
    image_urls: list[str] = Field(default_factory=list)
    benefits: list[str] = Field(default_factory=list)

    @field_validator("image_urls", "benefits", mode="before")
    @classmethod
    def _none_is_empty(cls, value: object) -> object:
        return value if value is not None else []

    model_config = {"from_attributes": True}


# -------------------------------------------------------- ticket categories ---


class TicketCategoryCreate(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=120)]
    description: str | None = None
    price_paise: Annotated[int, Field(ge=0, description="Price in paise, not rupees")]
    capacity: Annotated[int, Field(ge=0)]
    min_per_booking: Annotated[int, Field(default=1, ge=1)] = 1
    max_per_booking: Annotated[int, Field(default=10, ge=1)] = 10
    sort_order: Annotated[int, Field(default=0, ge=0)] = 0
    is_active: bool = True

    @model_validator(mode="after")
    def _check_limits(self) -> TicketCategoryCreate:
        if self.max_per_booking < self.min_per_booking:
            raise ValueError("max_per_booking must be at least min_per_booking")
        return self


class TicketCategoryUpdate(BaseModel):
    name: Annotated[str | None, Field(default=None, min_length=1, max_length=120)] = None
    description: str | None = None
    price_paise: Annotated[int | None, Field(default=None, ge=0)] = None
    capacity: Annotated[int | None, Field(default=None, ge=0)] = None
    min_per_booking: Annotated[int | None, Field(default=None, ge=1)] = None
    max_per_booking: Annotated[int | None, Field(default=None, ge=1)] = None
    sort_order: Annotated[int | None, Field(default=None, ge=0)] = None
    is_active: bool | None = None


class TicketCategoryPublic(BaseModel):
    """What a customer sees. Capacity and reservation counts are internal —
    exposing them tells a reseller exactly how much stock is left."""

    id: uuid.UUID
    name: str
    description: str | None = None
    price_paise: int
    currency: str
    available: int
    min_per_booking: int
    max_per_booking: int
    is_sold_out: bool

    model_config = {"from_attributes": True}


class TicketCategoryAdmin(BaseModel):
    id: uuid.UUID
    event_id: uuid.UUID
    name: str
    description: str | None = None
    price_paise: int
    currency: str
    capacity: int
    reserved_count: int
    sold_count: int
    available: int
    min_per_booking: int
    max_per_booking: int
    sort_order: int
    is_active: bool

    model_config = {"from_attributes": True}


# ------------------------------------------------------------------ events ---


class EventCreate(BaseModel):
    title: Annotated[str, Field(min_length=1, max_length=200)]
    slug: Annotated[str | None, Field(default=None, max_length=160)] = None
    subtitle: Annotated[str | None, Field(default=None, max_length=300)] = None
    description: str | None = None
    category: EventCategory = EventCategory.OTHER
    venue_id: uuid.UUID
    starts_at: datetime
    ends_at: datetime | None = None
    timezone: Annotated[str, Field(default="Asia/Kolkata", max_length=64)] = "Asia/Kolkata"
    sale_starts_at: datetime | None = None
    sale_ends_at: datetime | None = None
    banner_image_url: Annotated[str | None, Field(default=None, max_length=1024)] = None
    thumbnail_image_url: Annotated[str | None, Field(default=None, max_length=1024)] = None
    gallery_image_urls: Annotated[
        list[Annotated[str, Field(max_length=1024)]] | None, Field(default=None, max_length=10)
    ] = None
    max_tickets_per_customer: Annotated[int, Field(default=4, ge=1, le=100)] = 4
    requires_attendee_name: bool = False
    cancellation_policy: dict[str, Any] | None = None
    terms_and_conditions: str | None = None
    location_url: LocationUrl = None
    is_featured: bool = False

    @field_validator("slug")
    @classmethod
    def _validate_slug(cls, value: str | None) -> str | None:
        if value is not None and not SLUG_PATTERN.match(value):
            raise ValueError("slug must be lowercase words separated by single hyphens")
        return value

    @model_validator(mode="after")
    def _check_dates(self) -> EventCreate:
        if self.ends_at and self.ends_at < self.starts_at:
            raise ValueError("ends_at must not be before starts_at")
        if self.sale_starts_at and self.sale_ends_at and self.sale_ends_at < self.sale_starts_at:
            raise ValueError("sale_ends_at must not be before sale_starts_at")
        return self


class EventUpdate(BaseModel):
    title: Annotated[str | None, Field(default=None, min_length=1, max_length=200)] = None
    slug: Annotated[str | None, Field(default=None, max_length=160)] = None
    subtitle: Annotated[str | None, Field(default=None, max_length=300)] = None
    description: str | None = None
    category: EventCategory | None = None
    venue_id: uuid.UUID | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    timezone: Annotated[str | None, Field(default=None, max_length=64)] = None
    sale_starts_at: datetime | None = None
    sale_ends_at: datetime | None = None
    banner_image_url: Annotated[str | None, Field(default=None, max_length=1024)] = None
    thumbnail_image_url: Annotated[str | None, Field(default=None, max_length=1024)] = None
    gallery_image_urls: Annotated[
        list[Annotated[str, Field(max_length=1024)]] | None, Field(default=None, max_length=10)
    ] = None
    max_tickets_per_customer: Annotated[int | None, Field(default=None, ge=1, le=100)] = None
    requires_attendee_name: bool | None = None
    cancellation_policy: dict[str, Any] | None = None
    terms_and_conditions: str | None = None
    location_url: LocationUrl = None
    is_featured: bool | None = None

    @field_validator("slug")
    @classmethod
    def _validate_slug(cls, value: str | None) -> str | None:
        if value is not None and not SLUG_PATTERN.match(value):
            raise ValueError("slug must be lowercase words separated by single hyphens")
        return value


class EventCancelRequest(BaseModel):
    reason: Annotated[str, Field(min_length=1, max_length=500)]
    refund_bookings: bool = Field(
        default=True,
        description="Queue full refunds for every confirmed booking",
    )


class EventListItem(BaseModel):
    """Card shape for the public listing — deliberately small."""

    id: uuid.UUID
    slug: str
    title: str
    subtitle: str | None = None
    category: EventCategory
    status: EventStatus
    starts_at: datetime
    timezone: str
    venue_name: str
    city: str
    thumbnail_image_url: str | None = None
    banner_image_url: str | None = None
    starting_price_paise: int | None = None
    is_featured: bool
    is_sold_out: bool


def _web_link(value: object) -> object:
    """http(s) links only, so `javascript:` and the like are never stored or put in an href."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if len(text) > 1024:
        raise ValueError("That link is too long.")
    if not re.match(r"^https?://\S+$", text, re.IGNORECASE):
        raise ValueError("Enter a full web link starting with https://")
    return text


LocationUrl = Annotated[str | None, BeforeValidator(_web_link)]


class PerformerIn(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=120)]
    role: Annotated[str | None, Field(default=None, max_length=200)] = None
    photo_url: Annotated[str | None, Field(default=None, max_length=1024)] = None
    performs_at: datetime | None = None

    @field_validator("name", "role", "photo_url", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value


class LineupReplace(BaseModel):
    """The whole lineup, in running order. Replaces whatever was there."""

    performers: Annotated[list[PerformerIn], Field(max_length=20)]


class PerformerOut(BaseModel):
    id: uuid.UUID
    name: str
    role: str | None = None
    photo_url: str | None = None
    performs_at: datetime | None = None

    model_config = {"from_attributes": True}


class PerformerPublic(BaseModel):
    name: str
    role: str | None = None
    photo_url: str | None = None
    performs_at: datetime | None = None


class EventDetail(BaseModel):
    """Full public detail page."""

    id: uuid.UUID
    slug: str
    title: str
    subtitle: str | None = None
    description: str | None = None
    category: EventCategory
    status: EventStatus
    starts_at: datetime
    ends_at: datetime | None = None
    timezone: str
    sale_starts_at: datetime | None = None
    sale_ends_at: datetime | None = None
    on_sale: bool
    venue: VenueOut
    banner_image_url: str | None = None
    thumbnail_image_url: str | None = None
    gallery_image_urls: list[str] = Field(default_factory=list)
    ticket_categories: list[TicketCategoryPublic] = Field(default_factory=list)
    lineup: list[PerformerPublic] = Field(default_factory=list)
    max_tickets_per_customer: int
    requires_attendee_name: bool
    cancellation_policy: dict[str, Any] | None = None
    terms_and_conditions: str | None = None
    location_url: str | None = None
    is_sold_out: bool


class EventAdminDetail(BaseModel):
    id: uuid.UUID
    slug: str
    title: str
    subtitle: str | None = None
    description: str | None = None
    category: EventCategory
    status: EventStatus
    venue: VenueOut
    starts_at: datetime
    ends_at: datetime | None = None
    timezone: str
    sale_starts_at: datetime | None = None
    sale_ends_at: datetime | None = None
    banner_image_url: str | None = None
    thumbnail_image_url: str | None = None
    gallery_image_urls: list[str] = Field(default_factory=list)
    max_tickets_per_customer: int
    requires_attendee_name: bool
    cancellation_policy: dict[str, Any] | None = None
    terms_and_conditions: str | None = None
    location_url: str | None = None
    is_featured: bool
    published_at: datetime | None = None
    cancelled_at: datetime | None = None
    cancellation_reason: str | None = None
    created_at: datetime
    ticket_categories: list[TicketCategoryAdmin] = Field(default_factory=list)
    performers: list[PerformerOut] = Field(default_factory=list)

    # Validated directly from the `Event` ORM row, unlike the public shapes
    # which are built from cached dictionaries. Without this every admin event
    # endpoint fails with "Input should be a valid dictionary".
    model_config = {"from_attributes": True}

    @field_validator("gallery_image_urls", mode="before")
    @classmethod
    def _gallery_default(cls, value: object) -> object:
        """The column is nullable; the contract is "a list, possibly empty".

        Coercing here keeps NULL out of the API surface, so a client never has
        to distinguish "no gallery" from "gallery not set".
        """
        return value if value is not None else []


class AvailabilityItem(BaseModel):
    ticket_category_id: uuid.UUID
    name: str
    price_paise: int
    available: int
    is_sold_out: bool


class EventAvailability(BaseModel):
    """Live availability, cached for only a second or two.

    Exact-to-the-second counts are not needed: the authoritative check happens
    inside the reservation transaction, and polling this endpoint is what most
    of the traffic during a drop actually is.
    """

    event_id: uuid.UUID
    checked_at: datetime
    total_available: int
    categories: list[AvailabilityItem]
