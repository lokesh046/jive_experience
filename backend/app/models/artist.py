"""Artists: the people shown on the homepage, kept by the company, not derived from events."""

from __future__ import annotations

from sqlalchemy import Boolean, CheckConstraint, Index, Integer, String, true
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Artist(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "artists"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    # One short line under the name: "Solo cello and vocals".
    note: Mapped[str | None] = mapped_column(String(200))
    photo_url: Mapped[str | None] = mapped_column(String(1024))
    show_on_home: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )
    # Position among all artists; the homepage shows the visible ones in this order.
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    __table_args__ = (
        CheckConstraint("char_length(btrim(name)) > 0", name="name_not_blank"),
        Index("ix_artists_show_on_home_sort_order", "show_on_home", "sort_order"),
    )
