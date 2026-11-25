"""Administrator view of the background worker: is it running, what is waiting, what failed."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.core.errors import NotFoundError
from app.core.job_labels import job_label
from app.dependencies import AdminJobsDep, RequireAdmin
from app.models.fulfilment import OutboxMessage, OutboxStatus
from app.schemas.jobs import (
    JobOut,
    JobPage,
    OverviewOut,
    QueueOut,
    RetryOut,
    ScheduleOut,
    WorkerOut,
)

router = APIRouter(tags=["admin: jobs"])


def _job(m: OutboxMessage) -> JobOut:
    return JobOut(
        id=m.id,
        topic=m.topic,
        label=job_label(m.topic),
        status=m.status.value,
        attempts=m.attempts,
        max_attempts=m.max_attempts,
        last_error=m.last_error,
        created_at=m.created_at,
        available_at=m.available_at,
        completed_at=m.completed_at,
        payload=m.payload,
    )


@router.get("/jobs/overview", response_model=OverviewOut, summary="Worker, queue and schedules")
async def overview(actor: RequireAdmin, service: AdminJobsDep) -> OverviewOut:
    now = datetime.now(UTC)
    snap = await service.health.snapshot(now)
    q = snap.queue
    return OverviewOut(
        worker_alive=snap.alive,
        worker_ever_seen=bool(snap.workers),
        workers=[
            WorkerOut(
                id=w.worker_id,
                host=w.host,
                started_at=w.started_at,
                last_seen_at=w.last_seen_at,
                seconds_since_seen=max(0, int((now - w.last_seen_at).total_seconds())),
            )
            for w in snap.workers[:5]
        ],
        queue=QueueOut(
            waiting=q.get("PENDING", 0),
            ready=q.get("ready", 0),
            running=q.get("PROCESSING", 0),
            failed=q.get("FAILED", 0),
            done_24h=q.get("DONE", 0),
            oldest_ready_seconds=q.get("oldest_ready_seconds", 0),
        ),
        schedules=[
            ScheduleOut(
                name=run.name,
                label=run.label,
                interval_seconds=run.interval_seconds,
                last_finished_at=run.last_finished_at,
                last_status=run.last_status,
                last_error=run.last_error,
                runs=run.runs,
                overdue=overdue,
            )
            for run, overdue in snap.schedules
        ],
    )


@router.get("/jobs", response_model=JobPage, summary="Jobs, filtered")
async def list_jobs(
    actor: RequireAdmin,
    service: AdminJobsDep,
    job_status: Annotated[OutboxStatus | None, Query(alias="status")] = None,
    topic: Annotated[str | None, Query(max_length=80)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=100)] = 25,
) -> JobPage:
    rows, total = await service.ops.jobs(
        status=job_status, topic=topic, limit=size, offset=(page - 1) * size
    )
    return JobPage(items=[_job(m) for m in rows], total=total, page=page, size=size)


@router.post("/jobs/retry-failed", response_model=RetryOut, summary="Retry every failed job")
async def retry_failed(
    actor: RequireAdmin,
    service: AdminJobsDep,
    topic: Annotated[str | None, Query(max_length=80)] = None,
) -> RetryOut:
    return RetryOut(retried=await service.retry(job_id=None, topic=topic, actor=actor))


@router.post("/jobs/{job_id}/retry", response_model=RetryOut, summary="Retry one failed job")
async def retry_job(job_id: uuid.UUID, actor: RequireAdmin, service: AdminJobsDep) -> RetryOut:
    count = await service.retry(job_id=job_id, topic=None, actor=actor)
    if count == 0:
        raise NotFoundError("That job is not failed, or no longer exists.", code="JOB_NOT_FAILED")
    return RetryOut(retried=count)


@router.delete(
    "/jobs/{job_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Discard a failed job"
)
async def discard_job(job_id: uuid.UUID, actor: RequireAdmin, service: AdminJobsDep) -> None:
    if not await service.discard(job_id, actor=actor):
        raise NotFoundError("That job is not failed, or no longer exists.", code="JOB_NOT_FAILED")
