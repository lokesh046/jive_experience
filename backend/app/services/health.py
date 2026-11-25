"""Is the background worker alive, and is work piling up? And if not, tell an administrator.

The worker cannot report its own death, so this runs in the API: it reads the worker's heartbeat
and the queue, and raises one alert per outage (and one when it recovers).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.job_labels import SCHEDULES
from app.models.ops import JobRun, WorkerHeartbeat
from app.models.user import User
from app.repositories.ops import OpsRepository
from app.repositories.site_setting import SiteSettingRepository
from app.services.audit import AuditService
from app.services.notification_center import NotificationCenter

logger = structlog.get_logger(__name__)

ALIVE_WITHIN = timedelta(seconds=60)  # seen this recently: running
ALERT_AFTER = timedelta(seconds=150)  # silent this long: raise the alarm
BACKLOG_AFTER = timedelta(minutes=10)  # ready work left waiting this long
STATE_KEY = "worker_health"


@dataclass(slots=True)
class Snapshot:
    workers: list[WorkerHeartbeat]
    alive: bool
    last_seen: datetime | None
    queue: dict[str, int]
    schedules: list[tuple[JobRun, bool]]  # with "overdue"


class HealthService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.ops = OpsRepository(session)
        self.state = SiteSettingRepository(session)

    async def snapshot(self, now: datetime) -> Snapshot:
        workers = list(await self.ops.workers())
        last_seen = workers[0].last_seen_at if workers else None
        alive = last_seen is not None and now - last_seen <= ALIVE_WITHIN
        queue = await self.ops.queue_counts(now=now, done_since=now - timedelta(hours=24))
        schedules = []
        for run in await self.ops.schedules():
            due_by = (run.last_finished_at or now) + timedelta(
                seconds=max(run.interval_seconds * 3, 120)
            )
            schedules.append((run, run.last_finished_at is not None and now > due_by))
        return Snapshot(workers, alive, last_seen, queue, schedules)

    async def check_and_alert(self, now: datetime) -> list[str]:
        """Compare reality with the last look; alert on a change. Returns what it raised."""
        raised: list[str] = []
        center = NotificationCenter(self.session)
        workers = list(await self.ops.workers())
        state = await self.state.get(STATE_KEY) or {}

        if workers:  # a server that has never run a worker has nothing to lose yet
            seen = workers[0].last_seen_at
            silent_for = now - seen
            if silent_for > ALERT_AFTER and not state.get("down"):
                minutes = max(1, int(silent_for.total_seconds() // 60))
                await center.notify_admins(
                    kind="system.worker_down",
                    category="system",
                    severity="critical",
                    title="The background worker has stopped",
                    body=(
                        f"Last seen {minutes} min ago. Until it runs again, tickets are not issued "
                        "or emailed, refunds are not sent and reminders do not go out."
                    ),
                    link="/admin/jobs",
                    dedup_key=f"worker_down:{seen.isoformat()}",
                )
                await self.state.put(STATE_KEY, {"down": seen.isoformat()}, updated_by=None)
                raised.append("worker_down")
            elif silent_for <= ALIVE_WITHIN and state.get("down"):
                await center.notify_admins(
                    kind="system.worker_back",
                    category="system",
                    title="The background worker is running again",
                    body="Waiting jobs are being worked through.",
                    link="/admin/jobs",
                    dedup_key=f"worker_back:{state['down']}",
                )
                await self.state.put(STATE_KEY, {}, updated_by=None)
                raised.append("worker_back")

        stuck = await self.ops.stuck_count(older_than=now - BACKLOG_AFTER)
        if stuck:
            await center.notify_admins(
                kind="system.backlog",
                category="system",
                severity="warn",
                title=f"{stuck} background job{'s' if stuck != 1 else ''} waiting too long",
                body="Work has been ready for over 10 minutes. The worker may be overloaded.",
                link="/admin/jobs",
                dedup_key=f"backlog:{now:%Y%m%d%H}",
            )
            raised.append("backlog")
        await self.session.commit()
        return raised


def schedule_label(name: str) -> str:
    return SCHEDULES.get(name, name)


class AdminJobsService:
    """What an administrator can do about jobs: look, retry, discard. Each change is audited."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.ops = OpsRepository(session)
        self.health = HealthService(session)
        self.audit = AuditService(session)

    async def retry(self, *, job_id: uuid.UUID | None, topic: str | None, actor: User) -> int:
        count = await self.ops.retry(job_id=job_id, topic=topic, now=datetime.now(UTC))
        if count:
            await self.audit.record(
                "jobs.retried",
                entity_type="outbox_message",
                entity_id=job_id,
                actor=actor,
                after={"count": count, "topic": topic},
            )
        await self.session.commit()
        return count

    async def discard(self, job_id: uuid.UUID, *, actor: User) -> bool:
        job = await self.ops.discard(job_id)
        if job is None:
            return False
        await self.audit.record(
            "jobs.discarded",
            entity_type="outbox_message",
            entity_id=job_id,
            actor=actor,
            before={"topic": job.topic, "error": (job.last_error or "")[:300]},
        )
        await self.session.commit()
        return True
