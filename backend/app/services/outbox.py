"""Transactional outbox.

Work that must happen *because* a business fact became true — issue tickets
for a confirmed booking, send the confirmation email — is written to the
`outbox_messages` table in the same transaction as the fact itself.

That is what makes it reliable. A task started after the commit is lost if the
process dies in between; a task started before it runs for a booking that
never existed. Writing the intent inside the transaction gives exactly-once
*production*, and the worker's retries give at-least-once *delivery*, so every
handler must be idempotent.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.fulfilment import OutboxMessage, OutboxStatus
from app.repositories.fulfilment import OutboxRepository

logger = structlog.get_logger(__name__)

# Every topic the worker knows how to handle. Producers import these rather
# than writing the string, so a typo is an ImportError instead of a message
# that sits in the queue until someone notices.
TOPIC_PAYMENT_CAPTURED = "payment.captured"
TOPIC_BOOKING_CONFIRMED = "booking.confirmed"
TOPIC_TICKETS_ISSUED = "tickets.issued"
TOPIC_BOOKING_CANCELLED = "booking.cancelled"
TOPIC_BOOKING_REMINDER = "booking.reminder"
TOPIC_REFUND_PROCESS = "refund.process"
TOPIC_REFUND_COMPLETED = "refund.completed"
TOPIC_EVENT_CANCELLED = "event.cancelled"
TOPIC_ENQUIRY_RECEIVED = "enquiry.received"
TOPIC_NEWSLETTER_SUBSCRIBED = "newsletter.subscribed"
TOPIC_WAITLIST_AVAILABLE = "waitlist.available"
TOPIC_NEWSLETTER_SEND = "newsletter.send"
TOPIC_BOOKING_ABANDONED = "booking.abandoned"
TOPIC_NOTIFICATION_EMAIL = "notification.email"
TOPIC_NOTIFICATION_PUSH = "notification.push"

# How soon each kind of job should run when the queue is busy. Lower runs first.
URGENT, NORMAL, REMINDER, BULK = 0, 1, 2, 3
# Jobs at this number or above are "background": they may use only some of the worker's slots.
BACKGROUND_FROM = REMINDER
TOPIC_PRIORITY: dict[str, int] = {
    # Money and tickets: a person is waiting on these.
    TOPIC_PAYMENT_CAPTURED: URGENT,
    TOPIC_BOOKING_CONFIRMED: URGENT,
    TOPIC_REFUND_PROCESS: URGENT,
    TOPIC_EVENT_CANCELLED: URGENT,
    # Everyday mail and alerts.
    TOPIC_TICKETS_ISSUED: NORMAL,
    TOPIC_BOOKING_CANCELLED: NORMAL,
    TOPIC_REFUND_COMPLETED: NORMAL,
    TOPIC_ENQUIRY_RECEIVED: NORMAL,
    TOPIC_NEWSLETTER_SUBSCRIBED: NORMAL,
    TOPIC_WAITLIST_AVAILABLE: NORMAL,
    TOPIC_NOTIFICATION_EMAIL: NORMAL,
    TOPIC_NOTIFICATION_PUSH: NORMAL,
    # Can come in thousands at once, and must never delay the above.
    TOPIC_BOOKING_REMINDER: REMINDER,
    TOPIC_BOOKING_ABANDONED: BULK,
    TOPIC_NEWSLETTER_SEND: BULK,
}


def priority_for(topic: str) -> int:
    return TOPIC_PRIORITY.get(topic, NORMAL)


BASE_RETRY_SECONDS = 30
MAX_RETRY_SECONDS = 3600


def retry_delay(attempts: int) -> timedelta:
    """Exponential backoff, capped.

    Capped because a provider outage should not push the next attempt days
    out; a message still pending an hour later is an operational problem a
    human needs to see, not something to keep deferring.
    """
    seconds = min(BASE_RETRY_SECONDS * (2 ** max(attempts - 1, 0)), MAX_RETRY_SECONDS)
    return timedelta(seconds=seconds)


class OutboxService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.messages = OutboxRepository(session)

    async def enqueue(
        self,
        *,
        topic: str,
        payload: dict[str, Any],
        dedup_key: str | None = None,
        delay_seconds: int = 0,
    ) -> None:
        """Stage a message. **The caller commits.**

        With a `dedup_key` the insert is `ON CONFLICT DO NOTHING`, so a path
        that runs twice enqueues the work once — and, critically, the conflict
        does not abort the caller's transaction the way a raised
        IntegrityError would.
        """
        available_at = datetime.now(UTC) + timedelta(seconds=delay_seconds)
        values = {
            "topic": topic,
            "payload": payload,
            "status": OutboxStatus.PENDING,
            "available_at": available_at,
            "dedup_key": dedup_key,
            "priority": priority_for(topic),
        }

        statement = insert(OutboxMessage).values(**values)
        if dedup_key is not None:
            statement = statement.on_conflict_do_nothing(index_elements=["dedup_key"])
        await self.session.execute(statement)

    async def enqueue_many(self, messages: list[dict[str, Any]]) -> None:
        for message in messages:
            await self.enqueue(**message)
