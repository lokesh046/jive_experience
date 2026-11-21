"""Page/size pagination, shared by every list endpoint.

`size` is capped so that no caller can ask for an unbounded result set.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Query
from pydantic import BaseModel, Field

MAX_PAGE_SIZE = 100


class PageParams(BaseModel):
    page: Annotated[int, Query(ge=1)] = 1
    size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 20

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.size

    @property
    def limit(self) -> int:
        return self.size


class Page[T](BaseModel):
    """Offset-paginated envelope."""

    items: list[T]
    total: int = Field(description="Total rows matching the filter")
    page: int
    size: int

    @property
    def pages(self) -> int:
        return (self.total + self.size - 1) // self.size if self.size else 0

    @classmethod
    def build(cls, items: list[T], *, total: int, params: PageParams) -> Page[T]:
        return cls(items=items, total=total, page=params.page, size=params.size)
