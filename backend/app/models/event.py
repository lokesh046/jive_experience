"""Events and their ticket categories.

An event is the thing being sold; a ticket category is a price band within it
(General, VIP, Early Bird) and is also the unit of inventory.

Inventory counters live on `ticket_categories` deliberately. Availability is
`capacity - sold_count - reserved_count`, maintained by conditional UPDATEs so
that two simultaneous buyers of the last ticket cannot both succeed. The CHECK
constraints below make overselling impossible even if the application layer is
wrong — see `app/services/inventory.py`.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, money_column

if TYPE_CHECKING:  # pragma: no cover
    from app.models.venue import Venue


class EventStatus(StrEnum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SOLD_OUT = "SOLD_OUT"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class EventCategory(StrEnum):
    CONCERT = "CONCERT"
    MUSIC_FESTIVAL = "MUSIC_FESTIVAL"
    DJ_EVENT = "DJ_EVENT"
    CULTURAL = "CULTURAL"
    CELEBRITY = "CELEBRITY"
    CORPORATE = "CORPORATE"
    EXHIBITION = "EXHIBITION"
    PRODUCT_LAUNCH = "PRODUCT_LAUNCH"
    BRAND_ACTIVATION = "BRAND_ACTIVATION"
    PRIVATE_CELEBRATION = "PRIVATE_CELEBRATION"
    DESTINATION = "DESTINATION"
    OTHER = "OTHER"


event_status_enum = Enum(
    EventStatus,
    name="event_status",
    values_callable=lambda enum: [member.value for member in enum],
)
event_category_enum = Enum(
    EventCategory,
    name="event_category",
    values_callable=lambda enum: [member.value for member in enum],
)

PUBLIC_EVENT_STATUSES = (EventStatus.PUBLISHED, EventStatus.SOLD_OUT)
"""Statuses a customer may see. DRAFT and CANCELLED are never listed."""


class Event(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "events"

    slug: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    subtitle: Mapped[str | None] = mapped_column(String(300))
    description: Mapped[str | None] = mapped_column(Text)

    status: Mapped[EventStatus] = mapped_column(
        event_status_enum, nullable=False, default=EventStatus.DRAFT, index=True
    )
    category: Mapped[EventCategory] = mapped_column(
        event_category_enum, nullable=False, default=EventCategory.OTHER
    )

    venue_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("venues.id", ondelete="RESTRICT"), nullable=False
    )

    # Stored UTC; `timezone` is the event's local zone for display.
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Asia/Kolkata")

    # Sale window. Outside it no reservation may be created.
    sale_starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sale_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # References only — the bytes live in object storage or behind a CDN, so
    # the API never serves images and the frontend can resize at the edge.
    banner_image_url: Mapped[str | None] = mapped_column(String(1024))
    thumbnail_image_url: Mapped[str | None] = mapped_column(String(1024))
    gallery_image_urls: Mapped[list[str] | None] = mapped_column(JSONB)

    # Per-event policy the administrator sets. Enforced across *all* of a
    # customer's bookings for the event, not per booking.
    max_tickets_per_customer: Mapped[int] = mapped_column(Integer, nullable=False, default=4)
    requires_attendee_name: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Refund tiers, e.g. {"tiers": [{"hours_before": 168, "percent": 100}]}.
    # Interpreted by app/services/refund.py. Shape is settled; the actual
    # numbers are a client decision — see docs/open-decisions.md.
    cancellation_policy: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    terms_and_conditions: Mapped[str | None] = mapped_column(Text)

    is_featured: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancellation_reason: Mapped[str | None] = mapped_column(String(500))

    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    ticket_categories: Mapped[list[TicketCategory]] = relationship(
        back_populates="event", cascade="all, delete-orphan", lazy="selectin"
    )
    venue: Mapped[Venue] = relationship(lazy="joined")
    performers: Mapped[list[EventPerformer]] = relationship(
        back_populates="event",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="EventPerformer.sort_order",
    )

    __table_args__ = (
        CheckConstraint("ends_at IS NULL OR ends_at >= starts_at", name="ends_after_start"),
        CheckConstraint(
            "sale_ends_at IS NULL OR sale_starts_at IS NULL OR sale_ends_at >= sale_starts_at",
            name="sale_window_ordered",
        ),
        CheckConstraint("max_tickets_per_customer > 0", name="purchase_limit_positive"),
        CheckConstraint(
            "(status <> 'PUBLISHED') OR (published_at IS NOT NULL)",
            name="published_event_has_timestamp",
        ),
        # The public listing: published events, upcoming first.
        Index("ix_events_status_starts_at", "status", "starts_at"),
        Index("ix_events_venue_id", "venue_id"),
        Index("ix_events_category_starts_at", "category", "starts_at"),
        # Partial index for the homepage's featured strip.
        Index(
            "ix_events_featured",
            "starts_at",
            postgresql_where="is_featured AND status = 'PUBLISHED'",
        ),
    )


class TicketCategory(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A price band, and the unit of inventory.

    `reserved_count` is held by live reservations; `sold_count` by confirmed
    bookings. Availability is `capacity - sold_count - reserved_count` and is
    never allowed to go negative — the CHECK constraint is the backstop behind
    the conditional UPDATE in the inventory service.
    """

    __tablename__ = "ticket_categories"

    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("events.id", ondelete="CASCADE"), nullable=False
    )

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    price_paise: Mapped[int] = money_column(default=0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")

    capacity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reserved_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sold_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    min_per_booking: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    max_per_booking: Mapped[int] = mapped_column(Integer, nullable=False, default=10)

    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    event: Mapped[Event] = relationship(back_populates="ticket_categories")

    __table_args__ = (
        UniqueConstraint("event_id", "name", name="uq_ticket_categories_event_id_name"),
        CheckConstraint("price_paise >= 0", name="price_not_negative"),
        CheckConstraint("capacity >= 0", name="capacity_not_negative"),
        CheckConstraint("reserved_count >= 0", name="reserved_not_negative"),
        CheckConstraint("sold_count >= 0", name="sold_not_negative"),
        # The constraint that makes overselling impossible regardless of
        # application bugs or race conditions.
        CheckConstraint("reserved_count + sold_count <= capacity", name="not_oversold"),
        CheckConstraint(
            "min_per_booking >= 1 AND max_per_booking >= min_per_booking",
            name="booking_limits_ordered",
        ),
        Index("ix_ticket_categories_event_id_sort_order", "event_id", "sort_order"),
    )

    @property
    def available(self) -> int:
        return self.capacity - self.sold_count - self.reserved_count


class EventPerformer(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Someone on the bill for an event: shown on the event page as the lineup.

    The lineup is edited as a whole list (see `CatalogueService.replace_lineup`),
    so `sort_order` is simply the position in that list.
    """

    __tablename__ = "event_performers"

    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("events.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    role: Mapped[str | None] = mapped_column(String(200))
    photo_url: Mapped[str | None] = mapped_column(String(1024))
    # When they go on. Optional: a lineup can be announced before the times.
    performs_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    event: Mapped[Event] = relationship(back_populates="performers")

    __table_args__ = (Index("ix_event_performers_event_id_sort_order", "event_id", "sort_order"),)
