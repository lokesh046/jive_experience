"""Running jobs in parallel, urgent work first, and keeping within the email allowance."""

from __future__ import annotations

import asyncio
import time
import uuid
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import mailer
from app.core.config import Settings
from app.core.email_budget import EmailBudget, EmailDeferred
from app.core.mailer import Mail
from app.core.redis import close_redis, create_redis, get_redis
from app.repositories.fulfilment import OutboxRepository
from app.services.outbox import (
    BACKGROUND_FROM,
    BULK,
    NORMAL,
    REMINDER,
    TOPIC_BOOKING_ABANDONED,
    TOPIC_BOOKING_CONFIRMED,
    TOPIC_BOOKING_REMINDER,
    TOPIC_NEWSLETTER_SEND,
    TOPIC_PAYMENT_CAPTURED,
    TOPIC_REFUND_PROCESS,
    TOPIC_TICKETS_ISSUED,
    URGENT,
    OutboxService,
    priority_for,
)
from app.worker import Job, Worker

pytestmark = pytest.mark.integration


@pytest.fixture
async def redis(settings: Settings):  # type: ignore[no-untyped-def]
    create_redis(settings)
    yield get_redis()
    await close_redis()


# --------------------------------------------------------------- priorities ---


def test_money_and_tickets_are_urgent_and_bulk_mail_is_last() -> None:
    for urgent in (TOPIC_PAYMENT_CAPTURED, TOPIC_BOOKING_CONFIRMED, TOPIC_REFUND_PROCESS):
        assert priority_for(urgent) == URGENT
    assert priority_for(TOPIC_TICKETS_ISSUED) == NORMAL
    assert priority_for(TOPIC_BOOKING_REMINDER) == REMINDER
    assert priority_for(TOPIC_NEWSLETTER_SEND) == BULK == priority_for(TOPIC_BOOKING_ABANDONED)
    assert priority_for("something.new") == NORMAL
    assert BACKGROUND_FROM == REMINDER


async def test_a_ticket_jumps_a_queue_of_newsletters(db_session: AsyncSession) -> None:
    await db_session.execute(
        sa.text(
            "UPDATE outbox_messages SET available_at = now() + interval '10 years' "
            "WHERE status = 'PENDING'"
        )
    )
    outbox = OutboxService(db_session)
    tag = uuid.uuid4().hex[:8]
    for i in range(30):  # a newsletter queued first, a long time ago
        await outbox.enqueue(
            topic=TOPIC_NEWSLETTER_SEND, payload={"n": i}, dedup_key=f"news:{tag}:{i}"
        )
    await db_session.execute(
        sa.text(
            "UPDATE outbox_messages SET available_at = now() - interval '1 hour' "
            "WHERE dedup_key LIKE :k"
        ),
        {"k": f"news:{tag}:%"},
    )
    await outbox.enqueue(
        topic=TOPIC_TICKETS_ISSUED, payload={"booking_id": "t"}, dedup_key=f"ticket:{tag}"
    )
    await outbox.enqueue(
        topic=TOPIC_PAYMENT_CAPTURED, payload={"payment_id": "p"}, dedup_key=f"pay:{tag}"
    )
    await db_session.commit()

    claimed = await OutboxRepository(db_session).claim(
        worker_id="t", now=datetime.now(UTC), limit=5
    )
    topics = [m.topic for m in claimed]
    # Five places, thirty newsletters waiting an hour: the payment and the ticket still get in.
    assert {TOPIC_PAYMENT_CAPTURED, TOPIC_TICKETS_ISSUED} <= set(topics)
    assert topics.count(TOPIC_NEWSLETTER_SEND) == 3

    # The background lane can be claimed on its own, and the front lane never takes it.
    front = await OutboxRepository(db_session).claim(
        worker_id="t", now=datetime.now(UTC), limit=50, max_priority=BACKGROUND_FROM - 1
    )
    assert all(m.priority < BACKGROUND_FROM for m in front)


async def test_a_job_put_off_keeps_its_attempts(db_session: AsyncSession) -> None:
    await db_session.execute(
        sa.text(
            "UPDATE outbox_messages SET available_at = now() + interval '10 years' "
            "WHERE status = 'PENDING'"
        )
    )
    await OutboxService(db_session).enqueue(
        topic=TOPIC_NEWSLETTER_SEND, payload={"x": 1}, dedup_key=f"defer:{uuid.uuid4().hex}"
    )
    await db_session.commit()
    repo = OutboxRepository(db_session)
    (job,) = await repo.claim(worker_id="t", now=datetime.now(UTC), limit=1)
    job_id = job.id
    assert job.attempts == 1
    later = datetime.now(UTC) + timedelta(hours=5)
    await repo.defer(job_id, until=later, reason="Allowance used up")
    db_session.expire_all()
    row = (
        await db_session.execute(
            sa.text(
                "SELECT status::text, attempts, available_at, last_error "
                "FROM outbox_messages WHERE id = :i"
            ),
            {"i": job_id},
        )
    ).one()
    assert row[0] == "PENDING" and row[1] == 0 and row[2] > datetime.now(UTC) + timedelta(hours=4)
    assert row[3] == "Allowance used up"


# -------------------------------------------------------------- in parallel ---


async def test_a_worker_runs_jobs_in_parallel_with_room_kept_for_urgent_ones(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Jobs run side by side, and bulk work cannot fill every slot."""
    worker = Worker(
        settings.model_copy(
            update={
                "worker_concurrency": 8,
                "worker_background_slots": 5,
                "worker_poll_interval_seconds": 0.05,
            }
        )
    )
    queue: list[Job] = [Job(uuid.uuid4(), "test.bulk", {}, 1, 8, BULK) for _ in range(12)] + [
        Job(uuid.uuid4(), "test.urgent", {}, 1, 8, URGENT) for _ in range(3)
    ]
    in_flight = {"bulk": 0, "peak_bulk": 0, "all": 0, "peak": 0}
    finished: list[str] = []

    async def claim(free: int, background_free: int) -> list[Job]:
        taken: list[Job] = []
        for job in [j for j in queue if j.priority < BACKGROUND_FROM][:free]:
            queue.remove(job)
            taken.append(job)
        room = min(free - len(taken), background_free)
        for job in [j for j in queue if j.priority >= BACKGROUND_FROM][: max(room, 0)]:
            queue.remove(job)
            taken.append(job)
        return taken

    async def handle(_session: object, job: Job) -> None:
        in_flight["all"] += 1
        in_flight["peak"] = max(in_flight["peak"], in_flight["all"])
        if job.priority >= BACKGROUND_FROM:
            in_flight["bulk"] += 1
            in_flight["peak_bulk"] = max(in_flight["peak_bulk"], in_flight["bulk"])
        await asyncio.sleep(0.3)
        in_flight["all"] -= 1
        if job.priority >= BACKGROUND_FROM:
            in_flight["bulk"] -= 1
        finished.append(job.topic)

    class _NoSession:
        async def __aenter__(self) -> None:
            return None

        async def __aexit__(self, *a: object) -> None:
            return None

    monkeypatch.setattr(worker, "_claim", claim)
    monkeypatch.setattr(worker, "_handle", handle)
    monkeypatch.setattr("app.worker.get_sessionmaker", lambda: lambda: _NoSession())

    started = time.monotonic()
    runner = asyncio.create_task(worker.run_outbox())
    while len(finished) < 15 and time.monotonic() - started < 10:
        await asyncio.sleep(0.05)
    worker.request_stop()
    await runner
    took = time.monotonic() - started

    assert len(finished) == 15
    assert took < 1.6, f"15 jobs of 0.3 s took {took:.1f}s: they ran one after another"
    assert in_flight["peak"] == 8
    assert in_flight["peak_bulk"] <= 5  # at least three slots always stay free for urgent work


# --------------------------------------------------------- the email budget ---


async def _budget(settings: Settings, **over: object) -> tuple[EmailBudget, dict[str, float]]:
    clock = {"now": 1_000_000.0 * 3600}  # an hour boundary keeps the arithmetic obvious
    sleeps: list[float] = []

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock["now"] += seconds

    kwargs: dict[str, object] = {
        "daily_limit": 10,
        "bulk_share": 0.5,
        "per_second": 0,
        "prefix": f"test:{uuid.uuid4().hex[:8]}",
    }
    kwargs.update(over)
    budget = EmailBudget(get_redis(), clock=lambda: clock["now"], sleep=sleep, **kwargs)  # type: ignore[arg-type]
    clock["sleeps"] = sleeps  # type: ignore[assignment]
    return budget, clock


async def test_bulk_mail_may_use_only_its_share_and_tickets_keep_the_rest(
    redis: object,
    settings: Settings,
) -> None:
    budget, clock = await _budget(settings)
    for _ in range(5):
        await budget.acquire(bulk=True)
    with pytest.raises(EmailDeferred) as bulk:
        await budget.acquire(bulk=True)  # the 6th newsletter must wait
    assert bulk.value.until.timestamp() > clock["now"]
    for _ in range(5):
        await budget.acquire(bulk=False)  # tickets still have their half
    with pytest.raises(EmailDeferred):
        await budget.acquire(bulk=False)  # and then even they wait
    assert await budget.used() == 10  # refused attempts did not use anything up


async def test_an_email_that_failed_gives_its_place_back(redis: object, settings: Settings) -> None:
    budget, _ = await _budget(settings, daily_limit=2)
    first = await budget.acquire(bulk=False)
    await budget.acquire(bulk=False)
    with pytest.raises(EmailDeferred):
        await budget.acquire(bulk=False)
    await budget.release(first)
    await budget.acquire(bulk=False)  # room again


async def test_the_allowance_frees_up_as_old_hours_roll_out_of_the_window(
    redis: object,
    settings: Settings,
) -> None:
    budget, clock = await _budget(settings, daily_limit=3, bulk_share=1.0)
    for _ in range(3):
        await budget.acquire(bulk=False)
    with pytest.raises(EmailDeferred) as full:
        await budget.acquire(bulk=False)
    # It is told to come back when the hour those three were sent in is 24 hours old.
    expected = clock["now"] // 3600 * 3600 + 24 * 3600
    assert expected <= full.value.until.timestamp() <= expected + 120
    clock["now"] = expected + 120
    await budget.acquire(bulk=False)  # a day later there is room again


async def test_sending_is_paced_to_the_rate_the_provider_allows(
    redis: object, settings: Settings
) -> None:
    budget, clock = await _budget(settings, daily_limit=0, per_second=2)
    for _ in range(5):
        await budget.acquire(bulk=False)
    sleeps = clock["sleeps"]
    assert len(sleeps) >= 2  # five emails at two a second cannot all go in one second
    assert all(0 < s <= 1.1 for s in sleeps)  # type: ignore[union-attr]


async def test_mail_that_must_wait_is_deferred_not_failed(
    redis: object, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The mailer turns "no room today" into a deferral, and never opens a connection for it."""
    on = settings.model_copy(
        update={
            "smtp_host": "smtp.example.com",
            "smtp_username": "u",
            "smtp_password": __import__("pydantic").SecretStr("p"),
            "mail_from": "x@example.com",
            "email_daily_limit": 1,
            "email_bulk_share": 1.0,
        }
    )
    key = f"test:{uuid.uuid4().hex[:8]}"
    monkeypatch.setattr(
        mailer,
        "_budget",
        lambda s: EmailBudget(get_redis(), daily_limit=1, bulk_share=1.0, per_second=0, prefix=key),
    )
    sent: list[str] = []
    monkeypatch.setattr(mailer, "_send_blocking", lambda s, m: sent.append(str(m["To"])))
    mail = Mail(to="a@example.org", subject="s", text="t", html="h")
    await mailer.send_mail(on, mail)
    with pytest.raises(EmailDeferred):
        await mailer.send_mail(on, mail, bulk=True)
    assert sent == ["a@example.org"]
