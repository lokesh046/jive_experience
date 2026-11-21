"""Venues.

Separate from events because one venue hosts many events, and the address,
map coordinates and capacity are properties of the place rather than of any
single show. The city lives here, which is what the public event list filters
on.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import CheckConstraint, Index, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Venue(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "venues"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    address_line1: Mapped[str] = mapped_column(String(200), nullable=False)
    address_line2: Mapped[str | None] = mapped_column(String(200))
    city: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    state: Mapped[str | None] = mapped_column(String(100))
    postal_code: Mapped[str | None] = mapped_column(String(20))
    country_code: Mapped[str] = mapped_column(String(2), nullable=False, default="IN")

    # Optional map pin. NUMERIC, not float: coordinates are compared and
    # displayed, never arithmetic-heavy, and exactness avoids drift.
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))

    # Physical capacity of the room. Advisory — ticket capacity is configured
    # per ticket category, because a venue may be sold in different layouts.
    seating_capacity: Mapped[int | None] = mapped_column()

    directions: Mapped[str | None] = mapped_column(Text)
    map_url: Mapped[str | None] = mapped_column(String(512))

    __table_args__ = (
        CheckConstraint(
            "latitude IS NULL OR (latitude BETWEEN -90 AND 90)", name="latitude_in_range"
        ),
        CheckConstraint(
            "longitude IS NULL OR (longitude BETWEEN -180 AND 180)",
            name="longitude_in_range",
        ),
        CheckConstraint(
            "seating_capacity IS NULL OR seating_capacity >= 0",
            name="seating_capacity_not_negative",
        ),
        # The public list filters by city and the admin list sorts by name.
        Index("ix_venues_city_name", "city", "name"),
    )
