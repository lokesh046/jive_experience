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
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.core.redis import close_redis, create_redis, get_redis
from app.db.session import create_engine, dispose_engine, get_sessionmaker
from app.models.fulfilment import OutboxMessage
from app.repositories.fulfilment import OutboxRepository
from app.services.booking import BookingService
from app.services.cache import CatalogueCache
from app.services.catalogue import CatalogueService
from app.services.inventory import InventoryService
from app.services.notification import NotificationService
from app.services.outbox import (
    TOPIC_BOOKING_CANCELLED,
    TOPIC_BOOKING_CONFIRMED,
    TOPIC_EVENT_CANCELLED,
    TOPIC_PAYMENT_CAPTURED,
    TOPIC_REFUND_COMPLETED,
    TOPIC_REFUND_PROCESS,
    TOPIC_TICKETS_ISSUED,
    OutboxService,
    retry_delay,
)
from app.services.payment import PaymentService
from app.services.payment_provider import get_payment_provider
from app.services.refund import RefundService
from app.services.ticket import TicketService

logger = structlog.get_logger("worker")

STALE_LOCK_MINUTES = 15

Handler = Callable[[AsyncSession, dict[str, Any]], Awaitable[None]]


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


async def handle_refund_process(session: AsyncSession, payload: dict[str, Any]) -> None:
    """Send a requested refund to the provider."""
    settings = get_settings()
    outbox = OutboxService(session)
    provider = get_payment_provider(settings.payment_provider)
    refunds = RefundService(session, settings, provider, outbox)
    status = await refunds.process_pending(uuid.UUID(payload["refund_id"]))
    logger.info("refund_processed", refund_id=payload["refund_id"], status=status.value)


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


def _notifications(session: AsyncSession) -> NotificationService:
    settings = get_settings()
    return NotificationService(session, settings, TicketService(session, OutboxService(session)))


async def handle_booking_cancelled(session: AsyncSession, payload: dict[str, Any]) -> None:
    sent = await _notifications(session).send_cancellation(uuid.UUID(payload["booking_id"]))
    logger.info("cancellation_email_handled", booking_id=payload["booking_id"], sent=sent)


async def handle_refund_completed(session: AsyncSession, payload: dict[str, Any]) -> None:
    sent = await _notifications(session).send_refund(uuid.UUID(payload["refund_id"]))
    logger.info("refund_email_handled", refund_id=payload["refund_id"], sent=sent)


HANDLERS: dict[str, Handler] = {
    TOPIC_PAYMENT_CAPTURED: handle_payment_captured,
    TOPIC_BOOKING_CONFIRMED: handle_booking_confirmed,
    TOPIC_TICKETS_ISSUED: handle_tickets_issued,
    TOPIC_REFUND_PROCESS: handle_refund_process,
    TOPIC_EVENT_CANCELLED: handle_event_cancelled,
    TOPIC_BOOKING_CANCELLED: handle_booking_cancelled,
    TOPIC_REFUND_COMPLETED: handle_refund_completed,
}


# ------------------------------------------------------------------ worker ---


class Worker:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.worker_id = f"{socket.gethostname()}:{uuid.uuid4().hex[:8]}"
        self._stopping = asyncio.Event()

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
        sessionmaker = get_sessionmaker()
        while not self._stopping.is_set():
            processed = 0
            try:
                async with sessionmaker() as session:
                    processed = await self._drain_batch(session)
            except Exception:
                logger.exception("outbox_loop_error")

            # Back off only when idle; a full batch means more work is waiting.
            if processed == 0:
                await self._sleep(self.settings.worker_poll_interval_seconds)

    async def _drain_batch(self, session: AsyncSession) -> int:
        repository = OutboxRepository(session)
        now = datetime.now(UTC)
        claimed = await repository.claim(
            worker_id=self.worker_id, now=now, limit=self.settings.worker_batch_size
        )
        # The claim is committed immediately: if this process dies now the
        # rows are marked PROCESSING and the stale-lock sweep recovers them,
        # rather than being claimed again at once by a sibling.
        await session.commit()

        for message in claimed:
            await self._handle(session, message)
        return len(claimed)

    async def _handle(self, session: AsyncSession, message: OutboxMessage) -> None:
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
        except Exception as exc:
            await session.rollback()
            if attempts >= max_attempts:
                await repository.mark_failed(message_id, error=str(exc))
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

    async def _sweep(self, session: AsyncSession) -> None:
        settings = self.settings
        outbox = OutboxService(session)
        cache = CatalogueCache(get_redis())
        inventory = InventoryService(session, settings.reservation_hold_seconds)
        bookings = BookingService(session, settings, inventory, outbox)

        # 1. Expired holds go back on sale. The single most time-sensitive
        #    job during a drop — every second of delay is a seat nobody can
        #    buy.
        released = await inventory.sweep_expired()
        if released:
            await session.commit()
            await cache.invalidate_lists()

        # 2. Pending bookings whose hold ran out.
        await bookings.sweep_expired()

        # 3. Work abandoned by a worker that died mid-message.
        stale_before = datetime.now(UTC) - timedelta(minutes=STALE_LOCK_MINUTES)
        recovered = await OutboxRepository(session).release_stale_locks(older_than=stale_before)
        if recovered:
            await session.commit()
            logger.info("outbox_stale_locks_released", count=recovered)

        # 4. Payments and refunds the provider never finished telling us
        #    about. Skipped while no provider is configured.
        if settings.payment_provider:
            provider = get_payment_provider(settings.payment_provider)
            refunds = RefundService(session, settings, provider, outbox)
            payments = PaymentService(session, settings, provider, bookings, refunds)
            await payments.reconcile_in_flight()
            await refunds.reconcile_in_flight()


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
        await asyncio.gather(worker.run_outbox(), worker.run_sweeper())
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
