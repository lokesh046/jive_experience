"""Sales report contracts. Money is integer paise throughout."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel

from app.models.event import EventStatus


class SalesTotals(BaseModel):
    gross_paise: int
    refunded_paise: int
    net_paise: int
    tickets_sold: int
    bookings: int
    cancelled_bookings: int
    checked_in: int
    capacity: int


class SalesEventRow(SalesTotals):
    event_id: uuid.UUID
    title: str
    slug: str
    starts_at: datetime
    status: EventStatus


class SalesDay(BaseModel):
    day: date
    tickets: int
    gross_paise: int


class SalesCategoryRow(BaseModel):
    name: str
    price_paise: int
    capacity: int
    tickets_sold: int
    gross_paise: int
    is_active: bool


class SalesReport(BaseModel):
    summary: SalesTotals
    events: list[SalesEventRow]
    daily: list[SalesDay]
    # Only when a single event is asked for.
    categories: list[SalesCategoryRow]
    days: int
    timezone: str
    generated_at: datetime
