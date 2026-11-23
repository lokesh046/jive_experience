"""Artist contracts."""

from __future__ import annotations

import uuid
from typing import Annotated

from pydantic import BaseModel, Field, field_validator


def _clean(value: object) -> object:
    if isinstance(value, str):
        return value.strip() or None
    return value


def _https(value: str | None) -> str | None:
    if value is not None and not value.lower().startswith(("https://", "http://")):
        raise ValueError("The photo must be a web address.")
    return value


class ArtistIn(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=120)]
    note: Annotated[str | None, Field(default=None, max_length=200)] = None
    photo_url: Annotated[str | None, Field(default=None, max_length=1024)] = None
    show_on_home: bool = True

    @field_validator("name", "note", "photo_url", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        return _clean(value)

    @field_validator("photo_url")
    @classmethod
    def _photo(cls, value: str | None) -> str | None:
        return _https(value)


class ArtistUpdate(BaseModel):
    """Only the fields sent are changed."""

    name: Annotated[str | None, Field(default=None, min_length=1, max_length=120)] = None
    note: Annotated[str | None, Field(default=None, max_length=200)] = None
    photo_url: Annotated[str | None, Field(default=None, max_length=1024)] = None
    show_on_home: bool | None = None

    @field_validator("name", "note", "photo_url", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        return _clean(value)

    @field_validator("photo_url")
    @classmethod
    def _photo(cls, value: str | None) -> str | None:
        return _https(value)


class ArtistOrder(BaseModel):
    """Every artist's id, in the order they should appear."""

    ids: Annotated[list[uuid.UUID], Field(max_length=500)]


class ArtistOut(BaseModel):
    id: uuid.UUID
    name: str
    note: str | None = None
    photo_url: str | None = None
    show_on_home: bool
    sort_order: int

    model_config = {"from_attributes": True}


class ArtistPublic(BaseModel):
    name: str
    note: str | None = None
    photo_url: str | None = None

    model_config = {"from_attributes": True}
