"""Background-jobs contracts."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel


class WorkerOut(BaseModel):
    id: str
    host: str
    started_at: datetime
    last_seen_at: datetime
    seconds_since_seen: int


class QueueOut(BaseModel):
    waiting: int  # ready or scheduled for later
    ready: int  # ready to run right now
    running: int
    failed: int
    done_24h: int
    oldest_ready_seconds: int


class ScheduleOut(BaseModel):
    name: str
    label: str
    interval_seconds: int
    last_finished_at: datetime | None
    last_status: str | None
    last_error: str | None
    runs: int
    overdue: bool


class EmailBudgetOut(BaseModel):
    enforced: bool
    limit: int
    bulk_cap: int
    used_24h: int
    per_second: float


class OverviewOut(BaseModel):
    worker_alive: bool
    worker_ever_seen: bool
    workers: list[WorkerOut]
    queue: QueueOut
    email: EmailBudgetOut
    schedules: list[ScheduleOut]


class JobOut(BaseModel):
    id: uuid.UUID
    topic: str
    label: str
    status: str
    attempts: int
    max_attempts: int
    priority: int = 1
    last_error: str | None = None
    created_at: datetime
    available_at: datetime
    completed_at: datetime | None = None
    payload: dict[str, Any]


class JobPage(BaseModel):
    items: list[JobOut]
    total: int
    page: int
    size: int


class RetryOut(BaseModel):
    retried: int
