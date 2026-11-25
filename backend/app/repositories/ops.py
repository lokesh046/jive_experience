from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any, cast

from sqlalchemy import CursorResult, delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.fulfilment import OutboxMessage, OutboxStatus
from app.models.ops import JobRun, WorkerHeartbeat


class OpsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ------------------------------------------------------------ heartbeat ---

    async def beat(self, *, worker_id: str, host: str, now: datetime) -> None:
        statement = (
            insert(WorkerHeartbeat)
            .values(worker_id=worker_id, host=host, started_at=now, last_seen_at=now)
            .on_conflict_do_update(index_elements=["worker_id"], set_={"last_seen_at": now})
        )
        await self.session.execute(statement)

    async def workers(self) -> Sequence[WorkerHeartbeat]:
        result = await self.session.execute(
            select(WorkerHeartbeat).order_by(WorkerHeartbeat.last_seen_at.desc())
        )
        return result.scalars().all()

    async def forget_workers_before(self, cutoff: datetime) -> int:
        result = cast(
            "CursorResult[Any]",
            await self.session.execute(
                delete(WorkerHeartbeat).where(WorkerHeartbeat.last_seen_at < cutoff)
            ),
        )
        return int(result.rowcount or 0)

    # ------------------------------------------------------- recurring jobs ---

    async def record_run(
        self,
        *,
        name: str,
        label: str,
        interval_seconds: int,
        started: datetime,
        finished: datetime,
        error: str | None,
    ) -> None:
        values = {
            "name": name,
            "label": label,
            "interval_seconds": interval_seconds,
            "last_started_at": started,
            "last_finished_at": finished,
            "last_status": "ERROR" if error else "OK",
            "last_error": error[:2000] if error else None,
            "runs": 1,
        }
        statement = (
            insert(JobRun)
            .values(**values)
            .on_conflict_do_update(
                index_elements=["name"],
                set_={
                    "label": label,
                    "interval_seconds": interval_seconds,
                    "last_started_at": started,
                    "last_finished_at": finished,
                    "last_status": values["last_status"],
                    "last_error": values["last_error"],
                    "runs": JobRun.runs + 1,
                },
            )
        )
        await self.session.execute(statement)

    async def schedules(self) -> Sequence[JobRun]:
        result = await self.session.execute(select(JobRun).order_by(JobRun.name))
        return result.scalars().all()

    # ---------------------------------------------------------------- queue ---

    async def queue_counts(self, *, now: datetime, done_since: datetime) -> dict[str, int]:
        rows = (
            await self.session.execute(
                select(OutboxMessage.status, func.count())
                .where(
                    (OutboxMessage.status != OutboxStatus.DONE)
                    | (OutboxMessage.completed_at >= done_since)
                )
                .group_by(OutboxMessage.status)
            )
        ).all()
        counts = {r[0].value: int(r[1]) for r in rows}
        ready = await self.session.scalar(
            select(func.count()).where(
                OutboxMessage.status == OutboxStatus.PENDING, OutboxMessage.available_at <= now
            )
        )
        oldest = await self.session.scalar(
            select(func.min(OutboxMessage.available_at)).where(
                OutboxMessage.status == OutboxStatus.PENDING, OutboxMessage.available_at <= now
            )
        )
        counts["ready"] = int(ready or 0)
        counts["oldest_ready_seconds"] = int((now - oldest).total_seconds()) if oldest else 0
        return counts

    async def stuck_count(self, *, older_than: datetime) -> int:
        return int(
            await self.session.scalar(
                select(func.count()).where(
                    OutboxMessage.status == OutboxStatus.PENDING,
                    OutboxMessage.available_at <= older_than,
                )
            )
            or 0
        )

    async def jobs(
        self, *, status: OutboxStatus | None, topic: str | None, limit: int, offset: int
    ) -> tuple[Sequence[OutboxMessage], int]:
        conditions = []
        if status is not None:
            conditions.append(OutboxMessage.status == status)
        if topic:
            conditions.append(OutboxMessage.topic == topic)
        total = await self.session.scalar(select(func.count()).where(*conditions))
        order = (
            OutboxMessage.completed_at.desc().nulls_last()
            if status is OutboxStatus.DONE
            else OutboxMessage.created_at.desc()
        )
        rows = await self.session.execute(
            select(OutboxMessage).where(*conditions).order_by(order).limit(limit).offset(offset)
        )
        return rows.scalars().all(), int(total or 0)

    async def retry(self, *, job_id: uuid.UUID | None, topic: str | None, now: datetime) -> int:
        """Hand failed jobs back to the queue with a fresh set of attempts."""
        statement = (
            update(OutboxMessage)
            .where(OutboxMessage.status == OutboxStatus.FAILED)
            .values(
                status=OutboxStatus.PENDING,
                attempts=0,
                available_at=now,
                locked_at=None,
                locked_by=None,
            )
        )
        if job_id is not None:
            statement = statement.where(OutboxMessage.id == job_id)
        if topic:
            statement = statement.where(OutboxMessage.topic == topic)
        result = cast("CursorResult[Any]", await self.session.execute(statement))
        return int(result.rowcount or 0)

    async def discard(self, job_id: uuid.UUID) -> OutboxMessage | None:
        job = await self.session.get(OutboxMessage, job_id)
        if job is None or job.status is not OutboxStatus.FAILED:
            return None
        await self.session.delete(job)
        return job

    async def prune_done(self, *, older_than: datetime) -> int:
        result = cast(
            "CursorResult[Any]",
            await self.session.execute(
                delete(OutboxMessage).where(
                    OutboxMessage.status == OutboxStatus.DONE,
                    OutboxMessage.completed_at < older_than,
                )
            ),
        )
        return int(result.rowcount or 0)
