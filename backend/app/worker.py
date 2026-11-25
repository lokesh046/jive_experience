"""Background worker.

    python -m app.worker

A separate process from the API, deliberately:

* a slow email provider must not add latency to a checkout;
* the worker can be restarted, scaled or stopped without touching the API;
* each holds its own database pool, so a busy worker cannot starve the API of
  connections (`WORKER_DB_POOL_SIZE`).

Two loops run concurrently:

* **sweeper** — releases expired inventory holds, expires abandoned bookings,
  reconciles payments and refunds, recovers abandoned outbox messages;
* **outbox** — claims and performs queued work with retries and backoff.

Everything here is idempotent and retry-safe. The worker assumes it will be
killed mid-message, that messages will be delivered twice, and that several
copies of itself are running.
"""

from __future__ import annotations

import asyncio
import contextlib
import signal
import socket
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.email_budget import EmailDeferred
from app.core.job_labels import SCHEDULES
from app.core.logging import configure_logging
from app.core.redis import close_redis, create_redis, get_redis
from app.db.session import create_engine, dispose_engine, get_sessionmaker
from app.models.commerce import Booking, RefundStatus
from app.models.fulfilment import OutboxMessage
from app.repositories.fulfilment import OutboxRepository
from app.repositories.ops import OpsRepository
from app.services.abandoned import AbandonedBookingService
from app.services.booking import BookingService
from app.services.cache import CatalogueCache
from app.services.catalogue import CatalogueService
from app.services.inventory import InventoryService
from app.services.notification import NotificationService
from app.services.notification_center import NotificationCenter
from app.services.notify_events import Notifier
from app.services.outbox import (
    BACKGROUND_FROM,
    TOPIC_BOOKING_ABANDONED,
    TOPIC_BOOKING_CANCELLED,
    TOPIC_BOOKING_CONFIRMED,
    TOPIC_BOOKING_REMINDER,
    TOPIC_ENQUIRY_RECEIVED,
    TOPIC_EVENT_CANCELLED,
    TOPIC_NEWSLETTER_SEND,
    TOPIC_NEWSLETTER_SUBSCRIBED,
    TOPIC_NOTIFICATION_EMAIL,
    TOPIC_NOTIFICATION_PUSH,
    TOPIC_PAYMENT_CAPTURED,
    TOPIC_REFUND_COMPLETED,
    TOPIC_REFUND_PROCESS,
    TOPIC_TICKETS_ISSUED,
    TOPIC_WAITLIST_AVAILABLE,
    OutboxService,
    retry_delay,
)
from app.services.payment import PaymentService
from app.services.payment_provider import get_payment_provider
from app.services.push import PushService
from app.services.refund import RefundService
from app.services.ticket import TicketService
from app.services.waitlist import WaitlistService

logger = structlog.get_logger("worker")

STALE_LOCK_MINUTES = 15
HEARTBEAT_SECONDS = 15.0

Handler = Callable[[AsyncSession, dict[str, Any]], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class Job:
    """A claimed message, copied out so it can be worked on in its own session."""

    id: uuid.UUID
    topic: str
    payload: dict[str, Any]
    attempts: int
    max_attempts: int
    priority: int

    @classmethod
    def of(cls, m: OutboxMessage) -> Job:
        return cls(m.id, m.topic, m.payload, m.attempts, m.max_attempts, m.priority)


# --------------------------------------------------------------- handlers ---


async def handle_booking_confirmed(session: AsyncSession, payload: dict[str, Any]) -> None:
    """Issue the QR tickets for a confirmed booking.

    Notification failures are kept independent of issuance: the tickets are
    created and committed here, and the email is a separate outbox message. A
    bounced email must never leave a paying customer without tickets.
    """
    booking_id = uuid.UUID(payload["booking_id"])
    outbox = OutboxService(session)
    tickets = TicketService(session, outbox)
    issued = await tickets.issue_for_booking(booking_id)
    logger.info("booking_confirmed_handled", booking_id=str(booking_id), tickets=len(issued))
    booking = await session.get(Booking, booking_id)
    if booking is not None:
        await Notifier(session).sales_progress(booking.event_id)


async def handle_payment_captured(session: AsyncSession, payload: dict[str, Any]) -> None:
    """Finish a captured payment: confirm the booking, or refund it.

    The durable half of capture. The message is written in the same
    transaction as the capture itself, so if the API died in between, this is
    what completes the job rather than leaving a charged customer with a
    pending booking.
    """
    settings = get_settings()
    outbox = OutboxService(session)
    provider = get_payment_provider(settings.payment_provider, settings)
    inventory = InventoryService(session, settings.reservation_hold_seconds)
    bookings = BookingService(session, settings, inventory, outbox)
    refunds = RefundService(session, settings, provider, outbox)
    payments = PaymentService(session, settings, provider, bookings, refunds)

    await payments.finalise_captured(uuid.UUID(payload["payment_id"]))
    logger.info("payment_captured_finalised", payment_id=payload["payment_id"])


async def handle_tickets_issued(session: AsyncSession, payload: dict[str, Any]) -> None:
    """Email the tickets to the customer.

    A separate outbox message from issuance, so a bounced email is retried on
    its own and can never undo or delay the tickets themselves.
    """
    settings = get_settings()
    outbox = OutboxService(session)
    notifications = NotificationService(session, settings, TicketService(session, outbox))
    sent = await notifications.send_tickets(uuid.UUID(payload["booking_id"]))
    logger.info("tickets_email_handled", booking_id=payload.get("booking_id"), sent=sent)
    await Notifier(session).tickets_ready(uuid.UUID(payload["booking_id"]))


async def handle_refund_process(session: AsyncSession, payload: dict[str, Any]) -> None:
    """Send a requested refund to the provider."""
    settings = get_settings()
    outbox = OutboxService(session)
    provider = get_payment_provider(settings.payment_provider)
    refunds = RefundService(session, settings, provider, outbox)
    status = await refunds.process_pending(uuid.UUID(payload["refund_id"]))
    logger.info("refund_processed", refund_id=payload["refund_id"], status=status.value)
    if status is RefundStatus.FAILED:
        await Notifier(session).refund_failed(uuid.UUID(payload["refund_id"]))


async def handle_event_cancelled(session: AsyncSession, payload: dict[str, Any]) -> None:
    """Refund every confirmed booking for a cancelled event.

    Done in the worker, not in the request that cancelled the event: an event
    may carry thousands of bookings, and each refund is a provider call. The
    message is re-enqueued until every booking has been handled, so a restart
    halfway through resumes rather than starting over.
    """
    settings = get_settings()
    event_id = uuid.UUID(payload["event_id"])
    outbox = OutboxService(session)
    provider = get_payment_provider(settings.payment_provider)
    refunds = RefundService(session, settings, provider, outbox)
    catalogue = CatalogueService(session, CatalogueCache(get_redis()))

    event = await catalogue.admin_event(event_id)
    processed = await refunds.refund_event_bookings(event=event, limit=50)
    logger.info("event_cancellation_refunds", event_id=str(event_id), bookings=processed)

    if processed:
        # More may remain; come back for the next batch.
        await outbox.enqueue(
            topic=TOPIC_EVENT_CANCELLED,
            payload={"event_id": str(event_id)},
            dedup_key=f"event.cancelled:{event_id}:{uuid.uuid4().hex[:8]}",
            delay_seconds=5,
        )
        await session.commit()


async def handle_enquiry_received(session: AsyncSession, payload: dict[str, Any]) -> None:
    sent = await _notifications(session).send_enquiry(uuid.UUID(payload["enquiry_id"]))
    logger.info("enquiry_email_handled", enquiry_id=payload["enquiry_id"], sent=sent)
    await Notifier(session).enquiry_received(uuid.UUID(payload["enquiry_id"]))


async def handle_newsletter_subscribed(session: AsyncSession, payload: dict[str, Any]) -> None:
    sent = await _notifications(session).send_newsletter_welcome(
        uuid.UUID(payload["subscriber_id"])
    )
    logger.info("newsletter_welcome_handled", subscriber_id=payload["subscriber_id"], sent=sent)


async def handle_newsletter_send(session: AsyncSession, payload: dict[str, Any]) -> None:
    sent = await _notifications(session).send_campaign(
        uuid.UUID(payload["campaign_id"]), uuid.UUID(payload["subscriber_id"])
    )
    logger.info("newsletter_email_handled", subscriber_id=payload["subscriber_id"], sent=sent)


async def handle_booking_abandoned(session: AsyncSession, payload: dict[str, Any]) -> None:
    sent = await _notifications(session).send_abandoned(uuid.UUID(payload["booking_id"]))
    logger.info("abandoned_email_handled", booking_id=payload["booking_id"], sent=sent)


async def handle_notification_email(session: AsyncSession, payload: dict[str, Any]) -> None:
    sent = await _notifications(session).send_alert_email(uuid.UUID(payload["notification_id"]))
    logger.info("alert_email_handled", notification_id=payload["notification_id"], sent=sent)


async def handle_notification_push(session: AsyncSession, payload: dict[str, Any]) -> None:
    sent = await PushService(session, get_settings()).deliver_notification(
        uuid.UUID(payload["notification_id"])
    )
    logger.info("push_handled", notification_id=payload["notification_id"], devices=sent)


async def handle_waitlist_available(session: AsyncSession, payload: dict[str, Any]) -> None:
    sent = await _notifications(session).send_waitlist_available(uuid.UUID(payload["entry_id"]))
    logger.info("waitlist_email_handled", entry_id=payload["entry_id"], sent=sent)
    await Notifier(session).waitlist_available(uuid.UUID(payload["entry_id"]))


async def handle_booking_reminder(session: AsyncSession, payload: dict[str, Any]) -> None:
    sent = await _notifications(session).send_reminder(uuid.UUID(payload["booking_id"]))
    logger.info("reminder_email_handled", booking_id=payload["booking_id"], sent=sent)
    await Notifier(session).event_reminder(uuid.UUID(payload["booking_id"]))


def _notifications(session: AsyncSession) -> NotificationService:
    settings = get_settings()
    return NotificationService(session, settings, TicketService(session, OutboxService(session)))


async def handle_booking_cancelled(session: AsyncSession, payload: dict[str, Any]) -> None:
    sent = await _notifications(session).send_cancellation(uuid.UUID(payload["booking_id"]))
    logger.info("cancellation_email_handled", booking_id=payload["booking_id"], sent=sent)
    await Notifier(session).booking_cancelled(uuid.UUID(payload["booking_id"]))


async def handle_refund_completed(session: AsyncSession, payload: dict[str, Any]) -> None:
    sent = await _notifications(session).send_refund(uuid.UUID(payload["refund_id"]))
    logger.info("refund_email_handled", refund_id=payload["refund_id"], sent=sent)
    await Notifier(session).refund_completed(uuid.UUID(payload["refund_id"]))


HANDLERS: dict[str, Handler] = {
    TOPIC_PAYMENT_CAPTURED: handle_payment_captured,
    TOPIC_BOOKING_CONFIRMED: handle_booking_confirmed,
    TOPIC_TICKETS_ISSUED: handle_tickets_issued,
    TOPIC_REFUND_PROCESS: handle_refund_process,
    TOPIC_EVENT_CANCELLED: handle_event_cancelled,
    TOPIC_BOOKING_CANCELLED: handle_booking_cancelled,
    TOPIC_BOOKING_REMINDER: handle_booking_reminder,
    TOPIC_ENQUIRY_RECEIVED: handle_enquiry_received,
    TOPIC_WAITLIST_AVAILABLE: handle_waitlist_available,
    TOPIC_NEWSLETTER_SUBSCRIBED: handle_newsletter_subscribed,
    TOPIC_NEWSLETTER_SEND: handle_newsletter_send,
    TOPIC_BOOKING_ABANDONED: handle_booking_abandoned,
    TOPIC_NOTIFICATION_EMAIL: handle_notification_email,
    TOPIC_NOTIFICATION_PUSH: handle_notification_push,
    TOPIC_REFUND_COMPLETED: handle_refund_completed,
}


# ------------------------------------------------------------------ worker ---


class Worker:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.worker_id = f"{socket.gethostname()}:{uuid.uuid4().hex[:8]}"
        self._stopping = asyncio.Event()
        self._last_run: dict[str, float] = {}
        self._last_recorded: dict[str, float] = {}

    def request_stop(self) -> None:
        """Finish the message in hand, then exit."""
        logger.info("worker_stop_requested", worker_id=self.worker_id)
        self._stopping.set()

    async def _sleep(self, seconds: float) -> None:
        """Interruptible pause — a stop signal does not wait out the interval."""
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._stopping.wait(), timeout=seconds)

    # ---------------------------------------------------------- outbox ---

    async def run_outbox(self) -> None:
        """Work the queue, several jobs at once, urgent ones first.

        Most jobs spend their time waiting on a network (an email takes about a second), so a
        handful in flight at once multiplies how much one worker gets through. Each job has its
        own database session, and a slot is refilled the moment one finishes: a ticket that
        arrives mid-newsletter waits for a free slot, not for the whole batch.
        """
        slots = max(1, self.settings.worker_concurrency)
        background_cap = max(0, min(self.settings.worker_background_slots, slots - 1))
        running: dict[asyncio.Task[None], bool] = {}  # task -> is it background work?
        while not self._stopping.is_set():
            free = slots - len(running)
            claimed: list[Job] = []
            if free > 0:
                try:
                    background_busy = sum(running.values())
                    claimed = await self._claim(free, background_cap - background_busy)
                except Exception:
                    logger.exception("outbox_claim_error")
            for job in claimed:
                task = asyncio.create_task(self._process(job))
                running[task] = job.priority >= BACKGROUND_FROM
            if not running:
                await self._sleep(self.settings.worker_poll_interval_seconds)
                continue
            # A full house waits for any job to finish; otherwise look again after a short pause.
            done, _ = await asyncio.wait(
                running,
                timeout=None
                if len(running) >= slots
                else self.settings.worker_poll_interval_seconds,
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in done:
                running.pop(task, None)
        if running:  # on the way out, let jobs in hand finish
            await asyncio.wait(running)

    async def _claim(self, free: int, background_free: int) -> list[Job]:
        """Take work: everything urgent or normal first, then background work in its own slots."""
        sessionmaker = get_sessionmaker()
        now = datetime.now(UTC)
        jobs: list[Job] = []
        async with sessionmaker() as session:
            repository = OutboxRepository(session)
            front = await repository.claim(
                worker_id=self.worker_id,
                now=now,
                limit=free,
                max_priority=BACKGROUND_FROM - 1,
            )
            jobs += [Job.of(m) for m in front]
            left = min(free - len(front), background_free)
            if left > 0:
                back = await repository.claim(
                    worker_id=self.worker_id, now=now, limit=left, min_priority=BACKGROUND_FROM
                )
                jobs += [Job.of(m) for m in back]
            # Committed at once: if this process dies now the rows read PROCESSING and the
            # stale-lock sweep recovers them, rather than a sibling claiming them again.
            await session.commit()
        return jobs

    async def _process(self, job: Job) -> None:
        try:
            async with get_sessionmaker()() as session:
                await self._handle(session, job)
        except Exception:
            logger.exception("outbox_job_error", topic=job.topic)

    async def _handle(self, session: AsyncSession, message: Job | OutboxMessage) -> None:
        repository = OutboxRepository(session)

        # Copy everything needed before the handler runs. A rollback expires
        # these attributes, and reading them afterwards triggers a lazy
        # refresh outside the async context — MissingGreenlet — which leaves
        # the message stuck in PROCESSING until the stale-lock sweep, turning
        # one failed job into a fifteen-minute stall.
        message_id = message.id
        topic = message.topic
        payload = message.payload
        attempts = message.attempts
        max_attempts = message.max_attempts

        handler = HANDLERS.get(topic)
        log = logger.bind(outbox_id=str(message_id), topic=topic, attempt=attempts)

        if handler is None:
            # An unknown topic is a deployment mismatch, not a transient
            # fault; retrying forever would hide it.
            await repository.mark_failed(message_id, error="No handler for topic")
            await session.commit()
            log.error("outbox_no_handler")
            return

        try:
            await handler(session, payload)
        except EmailDeferred as wait:
            # Not a failure: the day's email allowance is used up. Come back when there is room.
            await session.rollback()
            await repository.defer(message_id, until=wait.until, reason=wait.reason)
            await session.commit()
            log.info("outbox_message_deferred", until=wait.until.isoformat(), reason=wait.reason)
            return
        except Exception as exc:
            await session.rollback()
            if attempts >= max_attempts:
                await repository.mark_failed(message_id, error=str(exc))
                if topic not in (
                    TOPIC_NOTIFICATION_EMAIL,
                    TOPIC_NOTIFICATION_PUSH,
                ):  # no alerts about alerts
                    await Notifier(session).gave_up(topic, str(exc), message_id)
                await session.commit()
                log.error("outbox_message_failed_permanently", error=str(exc))
                return
            retry_at = datetime.now(UTC) + retry_delay(attempts)
            await repository.mark_retry(message_id, retry_at=retry_at, error=str(exc))
            await session.commit()
            log.warning("outbox_message_retry", error=str(exc), retry_at=retry_at.isoformat())
            return

        await repository.mark_done(message_id, now=datetime.now(UTC))
        await session.commit()
        log.info("outbox_message_done")

    # --------------------------------------------------------- sweeper ---

    async def run_sweeper(self) -> None:
        sessionmaker = get_sessionmaker()
        while not self._stopping.is_set():
            try:
                async with sessionmaker() as session:
                    await self._sweep(session)
            except Exception:
                logger.exception("sweeper_loop_error")
            await self._sleep(self.settings.worker_sweep_interval_seconds)

    async def _step(
        self,
        session: AsyncSession,
        name: str,
        interval: float,
        job: Callable[[], Awaitable[object]],
        *,
        enabled: bool = True,
    ) -> None:
        """Run one recurring job if it is due, and write down how it went.

        One failing step is logged and recorded, not allowed to stop the others: a broken
        reminder job must never stop expired holds going back on sale.
        """
        if not enabled:
            return
        now_m = time.monotonic()
        if now_m - self._last_run.get(name, -1e9) < interval:
            return
        self._last_run[name] = now_m
        started = datetime.now(UTC)
        error: str | None = None
        try:
            await job()
            await session.commit()
        except Exception as exc:
            await session.rollback()
            error = f"{type(exc).__name__}: {exc}"
            logger.exception("sweeper_step_failed", step=name)
        # Fast jobs run every few seconds: write their record at most every 30 s, but never
        # hide a failure or a first run.
        if error is None and now_m - self._last_recorded.get(name, -1e9) < 30:
            return
        self._last_recorded[name] = now_m
        try:
            await OpsRepository(session).record_run(
                name=name,
                label=SCHEDULES.get(name, name),
                interval_seconds=int(interval),
                started=started,
                finished=datetime.now(UTC),
                error=error,
            )
            await session.commit()
        except Exception:
            await session.rollback()
            logger.exception("job_run_record_failed", step=name)

    async def _sweep(self, session: AsyncSession) -> None:
        settings = self.settings
        every = settings.worker_sweep_interval_seconds
        outbox = OutboxService(session)
        cache = CatalogueCache(get_redis())
        inventory = InventoryService(session, settings.reservation_hold_seconds)
        bookings = BookingService(session, settings, inventory, outbox)

        async def release_holds() -> None:
            # The most time-sensitive job during a drop: every second of delay is a seat
            # nobody can buy.
            if await inventory.sweep_expired():
                await session.commit()
                await cache.invalidate_lists()

        async def recover_locks() -> None:
            stale_before = datetime.now(UTC) - timedelta(minutes=STALE_LOCK_MINUTES)
            recovered = await OutboxRepository(session).release_stale_locks(older_than=stale_before)
            if recovered:
                await session.commit()
                logger.info("outbox_stale_locks_released", count=recovered)

        async def reminders() -> None:
            notifications = NotificationService(session, settings, TicketService(session, outbox))
            queued = await notifications.enqueue_due_reminders(datetime.now(UTC))
            if queued:
                logger.info("reminders_queued", count=queued)

        async def abandoned() -> None:
            asked = await AbandonedBookingService(session, outbox).queue_due(datetime.now(UTC))
            if asked:
                logger.info("abandoned_reminders_queued", count=asked)

        async def doors() -> None:
            told = await Notifier(session).doors_open_soon(datetime.now(UTC))
            if told:
                logger.info("doors_notifications_sent", count=told)

        async def waitlist() -> None:
            told = await WaitlistService(session, outbox).notify_available()
            if told:
                logger.info("waitlist_notified", count=told)

        async def reconcile() -> None:
            provider = get_payment_provider(settings.payment_provider)
            refunds = RefundService(session, settings, provider, outbox)
            payments = PaymentService(session, settings, provider, bookings, refunds)
            await payments.reconcile_in_flight()
            await refunds.reconcile_in_flight()

        async def cleanup() -> None:
            now = datetime.now(UTC)
            await NotificationCenter(session, outbox).prune(now)
            await OpsRepository(session).prune_done(older_than=now - timedelta(days=30))
            await OpsRepository(session).forget_workers_before(now - timedelta(days=7))

        step = self._step
        await step(session, "release_holds", every, release_holds)
        await step(session, "expire_bookings", every, bookings.sweep_expired)
        await step(session, "recover_locks", every, recover_locks)
        await step(
            session,
            "reminders",
            settings.reminder_sweep_interval_seconds,
            reminders,
            enabled=settings.email_configured,
        )
        await step(
            session,
            "abandoned",
            settings.reminder_sweep_interval_seconds,
            abandoned,
            enabled=settings.email_configured,
        )
        await step(session, "doors", 300, doors)
        await step(session, "waitlist", settings.waitlist_sweep_interval_seconds, waitlist)
        await step(session, "reconcile", every, reconcile, enabled=bool(settings.payment_provider))
        await step(session, "cleanup", 6 * 3600, cleanup)

    # --------------------------------------------------------- heartbeat ---

    async def run_heartbeat(self) -> None:
        """Say "still here" every few seconds, so the API can tell when this process has died."""
        sessionmaker = get_sessionmaker()
        host = socket.gethostname()
        while not self._stopping.is_set():
            try:
                async with sessionmaker() as session:
                    await OpsRepository(session).beat(
                        worker_id=self.worker_id, host=host, now=datetime.now(UTC)
                    )
                    await session.commit()
            except Exception:
                logger.exception("heartbeat_failed")
            await self._sleep(HEARTBEAT_SECONDS)


# -------------------------------------------------------------- entrypoint ---


async def run() -> None:
    settings = get_settings()
    configure_logging(settings)

    # The worker's own pool, sized separately from the API's.
    create_engine(
        settings.model_copy(
            update={
                "db_pool_size": settings.worker_db_pool_size,
                "db_max_overflow": settings.worker_db_max_overflow,
            }
        )
    )
    create_redis(settings)

    worker = Worker(settings)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, worker.request_stop)

    logger.info(
        "worker_started",
        worker_id=worker.worker_id,
        batch_size=settings.worker_batch_size,
        poll_interval=settings.worker_poll_interval_seconds,
    )
    try:
        await asyncio.gather(worker.run_outbox(), worker.run_sweeper(), worker.run_heartbeat())
    finally:
        await close_redis()
        await dispose_engine()
        logger.info("worker_stopped", worker_id=worker.worker_id)


def main() -> int:
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(run())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
