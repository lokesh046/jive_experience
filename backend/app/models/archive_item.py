"""The archive: photos of past nights, shown on the homepage in an order the admin chooses."""

from __future__ import annotations

from sqlalchemy import Boolean, CheckConstraint, Index, Integer, String, true
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ArchiveItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "archive_items"

    # "Bandra Vinyl Salon, March 2027": shown under the photo.
    caption: Mapped[str | None] = mapped_column(String(200))
    photo_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    show_on_home: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    __table_args__ = (
        CheckConstraint("char_length(btrim(photo_url)) > 0", name="photo_not_blank"),
        Index("ix_archive_items_show_on_home_sort_order", "show_on_home", "sort_order"),
    )
