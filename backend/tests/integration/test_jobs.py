"""The jobs page and the worker health alert."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.repositories.ops import OpsRepository
from app.services.health import HealthService
from app.worker import Worker
from tests.integration.conftest import customer_session, seed_admin, sign_in_as
from tests.integration.google_stub import StubGoogleClient

pytestmark = pytest.mark.integration


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _job(session: AsyncSession, topic: str, status: str, **over: object) -> uuid.UUID:
    job_id = uuid.uuid4()
    await session.execute(
        sa.text(
            "INSERT INTO outbox_messages (id, topic, payload, status, attempts, max_attempts, "
            "available_at, last_error) VALUES (:i, :t, CAST(:p AS jsonb), "
            "CAST(:s AS outbox_status), :a, 8, :av, :e)"
        ),
        {
            "i": job_id,
            "t": topic,
            "p": '{"booking_id": "x"}',
            "s": status,
            "a": over.get("attempts", 8 if status == "FAILED" else 0),
            "av": over.get("available_at", datetime.now(UTC)),
            "e": over.get("error", "Boom" if status == "FAILED" else None),
        },
    )
    return job_id


async def _status(session: AsyncSession, job_id: uuid.UUID) -> str | None:
    session.expire_all()
    return (
        await session.execute(
            sa.text("SELECT status::text FROM outbox_messages WHERE id = :i"), {"i": job_id}
        )
    ).scalar_one_or_none()


# ------------------------------------------------------------------- the API ---


async def test_the_overview_and_job_list_show_what_is_failing(
    api: AsyncClient, db_session: AsyncSession, google: StubGoogleClient
) -> None:
    topic = f"test.{uuid.uuid4().hex[:8]}"
    await _job(db_session, topic, "FAILED", error="SMTP refused")
    await _job(db_session, topic, "PENDING")
    await _job(db_session, topic, "DONE")
    await db_session.commit()
    admin = await sign_in_as(api, google, await seed_admin(db_session))

    overview = (await api.get("/api/v1/admin/jobs/overview", headers=bearer(admin))).json()
    assert overview["queue"]["failed"] >= 1 and overview["queue"]["waiting"] >= 1
    assert "worker_alive" in overview and isinstance(overview["schedules"], list)

    failed = (
        await api.get(
            "/api/v1/admin/jobs", headers=bearer(admin), params={"status": "FAILED", "topic": topic}
        )
    ).json()
    assert failed["total"] == 1
    row = failed["items"][0]
    assert (
        row["last_error"] == "SMTP refused" and row["label"] == topic
    )  # unknown topics show as they are
    assert row["attempts"] == 8 and row["payload"] == {"booking_id": "x"}
    both = (
        await api.get("/api/v1/admin/jobs", headers=bearer(admin), params={"topic": topic})
    ).json()
    assert both["total"] == 3
    known = (
        await api.get(
            "/api/v1/admin/jobs",
            headers=bearer(admin),
            params={"topic": "tickets.issued", "size": 1},
        )
    ).json()
    assert known["items"] == [] or known["items"][0]["label"] == "Email the tickets"


async def test_failed_jobs_can_be_retried_one_or_all_and_discarded(
    api: AsyncClient, db_session: AsyncSession, google: StubGoogleClient
) -> None:
    topic = f"test.{uuid.uuid4().hex[:8]}"
    one, two, three = [await _job(db_session, topic, "FAILED") for _ in range(3)]
    live = await _job(db_session, topic, "PENDING")
    await db_session.commit()
    admin = await sign_in_as(api, google, await seed_admin(db_session))
    url = "/api/v1/admin/jobs"

    retried = await api.post(f"{url}/{one}/retry", headers=bearer(admin))
    assert retried.json() == {"retried": 1}
    assert await _status(db_session, one) == "PENDING"
    attempts = (
        await db_session.execute(
            sa.text("SELECT attempts FROM outbox_messages WHERE id = :i"), {"i": one}
        )
    ).scalar_one()
    assert attempts == 0  # a fresh set of tries

    # A job that is not failed cannot be retried or discarded.
    assert (await api.post(f"{url}/{live}/retry", headers=bearer(admin))).status_code == 404
    assert (await api.delete(f"{url}/{live}", headers=bearer(admin))).status_code == 404
    assert (await api.post(f"{url}/{uuid.uuid4()}/retry", headers=bearer(admin))).status_code == 404

    assert (await api.delete(f"{url}/{two}", headers=bearer(admin))).status_code == 204
    assert await _status(db_session, two) is None
    all_back = await api.post(f"{url}/retry-failed", headers=bearer(admin), params={"topic": topic})
    assert all_back.json() == {"retried": 1}
    assert await _status(db_session, three) == "PENDING"
    audited = (
        await db_session.execute(
            sa.text("SELECT count(*) FROM audit_logs WHERE action LIKE 'jobs.%'")
        )
    ).scalar_one()
    assert audited >= 3


async def test_only_admins_see_the_jobs(
    api: AsyncClient, db_session: AsyncSession, google: StubGoogleClient
) -> None:
    assert (await api.get("/api/v1/admin/jobs/overview")).status_code == 401
    customer = await customer_session(api, google)
    assert (
        await api.get("/api/v1/admin/jobs", headers=bearer(customer["access"]))
    ).status_code == 403
    assert (
        await api.post("/api/v1/admin/jobs/retry-failed", headers=bearer(customer["access"]))
    ).status_code == 403


# ------------------------------------------------------------ worker health ---


async def _only_worker(session: AsyncSession, seen_ago: timedelta | None) -> None:
    await session.execute(sa.text("DELETE FROM worker_heartbeats"))
    if seen_ago is not None:
        await session.execute(
            sa.text(
                "INSERT INTO worker_heartbeats (worker_id, host, started_at, last_seen_at) "
                "VALUES ('w1', 'host-a', now() - interval '1 day', :s)"
            ),
            {"s": datetime.now(UTC) - seen_ago},
        )
    await session.commit()
    session.expire_all()  # the raw SQL bypassed the session's cached rows


async def _alerts(session: AsyncSession, kind: str) -> int:
    return int(
        (
            await session.execute(
                sa.text("SELECT count(*) FROM notifications WHERE kind = :k"), {"k": kind}
            )
        ).scalar_one()
    )


async def test_a_silent_worker_raises_one_alarm_and_one_all_clear(db_session: AsyncSession) -> None:
    await seed_admin(db_session)
    await db_session.commit()
    health = HealthService(db_session)
    now = datetime.now(UTC)
    base = await _alerts(db_session, "system.worker_down")
    back = await _alerts(db_session, "system.worker_back")

    # Never ran: nothing to lose yet, so no alarm.
    await _only_worker(db_session, None)
    assert "worker_down" not in await health.check_and_alert(now)

    # Seen a minute ago: fine. Seen four minutes ago: alarm, but only once.
    await _only_worker(db_session, timedelta(minutes=1))
    assert "worker_down" not in await health.check_and_alert(now)
    await _only_worker(db_session, timedelta(minutes=4))
    assert "worker_down" in await health.check_and_alert(now)
    assert "worker_down" not in await health.check_and_alert(now + timedelta(minutes=1))
    assert await _alerts(db_session, "system.worker_down") > base

    snap = await health.snapshot(now)
    assert snap.alive is False and snap.last_seen is not None

    # It comes back: one all-clear.
    await _only_worker(db_session, timedelta(seconds=5))
    assert "worker_back" in await health.check_and_alert(now)
    assert "worker_back" not in await health.check_and_alert(now)
    assert await _alerts(db_session, "system.worker_back") > back
    assert (await health.snapshot(now)).alive is True


async def test_a_second_outage_is_a_second_alarm(db_session: AsyncSession) -> None:
    await seed_admin(db_session)
    health = HealthService(db_session)
    now = datetime.now(UTC)
    await _only_worker(db_session, timedelta(minutes=5))
    assert "worker_down" in await health.check_and_alert(now)
    await _only_worker(db_session, timedelta(seconds=3))
    await health.check_and_alert(now)
    await _only_worker(db_session, timedelta(minutes=6))
    assert "worker_down" in await health.check_and_alert(now)


async def test_work_waiting_too_long_raises_a_backlog_warning(db_session: AsyncSession) -> None:
    await seed_admin(db_session)
    await _only_worker(db_session, timedelta(seconds=3))
    await _job(
        db_session,
        f"test.{uuid.uuid4().hex[:8]}",
        "PENDING",
        available_at=datetime.now(UTC) - timedelta(minutes=30),
    )
    await db_session.commit()
    assert "backlog" in await HealthService(db_session).check_and_alert(datetime.now(UTC))


# ------------------------------------------------------------ the schedule ---


async def test_recurring_jobs_record_how_they_went_and_one_failure_does_not_stop_the_rest(
    db_session: AsyncSession, settings: Settings
) -> None:
    worker = Worker(settings)
    ran: list[str] = []

    async def fine() -> None:
        ran.append("fine")

    async def broken() -> None:
        raise RuntimeError("the reminder job broke")

    name_ok, name_bad = f"t_ok_{uuid.uuid4().hex[:6]}", f"t_bad_{uuid.uuid4().hex[:6]}"
    await worker._step(db_session, name_bad, 60, broken)
    await worker._step(db_session, name_ok, 60, fine)
    await worker._step(db_session, name_ok, 60, fine)  # not due again yet
    await worker._step(db_session, "t_off", 60, fine, enabled=False)
    assert ran == ["fine"]

    runs = {r.name: r for r in await OpsRepository(db_session).schedules()}
    assert runs[name_ok].last_status == "OK" and runs[name_ok].runs == 1
    assert runs[name_bad].last_status == "ERROR" and "the reminder job broke" in (
        runs[name_bad].last_error or ""
    )
    assert "t_off" not in runs


async def test_a_heartbeat_keeps_one_row_per_worker(db_session: AsyncSession) -> None:
    ops = OpsRepository(db_session)
    await db_session.execute(sa.text("DELETE FROM worker_heartbeats"))
    first = datetime.now(UTC) - timedelta(seconds=30)
    await ops.beat(worker_id="w9", host="h", now=first)
    await ops.beat(worker_id="w9", host="h", now=first + timedelta(seconds=15))
    workers = await ops.workers()
    assert len(workers) == 1 and workers[0].started_at == first
    assert workers[0].last_seen_at == first + timedelta(seconds=15)
