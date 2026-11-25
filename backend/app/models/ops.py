"""What the background worker reports about itself: that it is alive, and when each job last ran."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class WorkerHeartbeat(Base):
    """One row per worker process, refreshed every few seconds while it runs."""

    __tablename__ = "worker_heartbeats"

    worker_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    host: Mapped[str] = mapped_column(String(120), nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class JobRun(Base):
    """The last run of one recurring job (a sweeper step), so the schedule can be seen."""

    __tablename__ = "job_runs"

    name: Mapped[str] = mapped_column(String(60), primary_key=True)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    interval_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    last_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_status: Mapped[str | None] = mapped_column(String(10))  # OK or ERROR
    last_error: Mapped[str | None] = mapped_column(Text)
    runs: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
