"""Refunds.

Two things this module refuses to assume:

* **A gateway accepting a refund does not mean the money moved.** Refunds are
  a state machine — REQUESTED → PROCESSING → SUCCEEDED | FAILED — reconciled
  on a schedule. Nothing is marked refunded, and no ticket is invalidated,
  until the provider confirms settlement.
* **The refund policy is a business decision, not a default.** The tier shape
  is settled (`{"tiers": [{"hours_before": N, "percent": P}]}`); the numbers
  come from the client. Until an event carries a policy, only full refunds
  are offered — see `docs/open-decisions.md`.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import BusinessRuleError, ConflictError, NotFoundError
from app.core.money import percentage_of
from app.models.commerce import (
    Booking,
    BookingSource,
    BookingStatus,
    Payment,
    PaymentStatus,
    Refund,
    RefundReason,
    RefundStatus,
)
from app.models.event import Event
from app.models.fulfilment import TicketStatus
from app.models.site_setting import DEFAULT_CANCELLATION_POLICY
from app.models.user import User
from app.repositories.catalogue import EventRepository
from app.repositories.commerce import (
    BookingRepository,
    InventoryRepository,
    PaymentRepository,
    RefundRepository,
)
from app.repositories.fulfilment import TicketRepository
from app.repositories.site_setting import SiteSettingRepository
from app.services.audit import AuditService
from app.services.outbox import (
    TOPIC_BOOKING_CANCELLED,
    TOPIC_REFUND_COMPLETED,
    TOPIC_REFUND_PROCESS,
    OutboxService,
)
from app.services.payment_provider import PaymentProvider

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class RefundQuote:
    """What a cancellation would return, and why."""

    eligible: bool
    amount_paise: int
    percent: int
    reason: str


class RefundService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        provider: PaymentProvider,
        outbox: OutboxService,
    ) -> None:
        self.session = session
        self.settings = settings
        self.provider = provider
        self.outbox = outbox
        self.refunds = RefundRepository(session)
        self.payments = PaymentRepository(session)
        self.bookings = BookingRepository(session)
        self.inventory = InventoryRepository(session)
        self.tickets = TicketRepository(session)
        self.events = EventRepository(session)
        self.site_settings = SiteSettingRepository(session)
        self.audit = AuditService(session)

    # ------------------------------------------------------------ policy ---

    async def effective_policy(self, event: Event) -> dict[str, Any] | None:
        """The event's own policy, or the site default when it has none."""
        if event.cancellation_policy:
            return event.cancellation_policy
        return await self.site_settings.get(DEFAULT_CANCELLATION_POLICY)

    async def quote(
        self, *, booking: Booking, event: Event, now: datetime | None = None
    ) -> RefundQuote:
        """How much this booking would get back if cancelled now.

        With no policy configured the answer is "not self-serviceable" rather
        than a guessed percentage. Inventing a refund rule would be inventing
        a commercial term.
        """
        now = now or datetime.now(UTC)

        if booking.status is not BookingStatus.CONFIRMED:
            return RefundQuote(False, 0, 0, "Only a confirmed booking can be refunded.")
        if booking.source is not BookingSource.ONLINE:
            return RefundQuote(
                False, 0, 0, "These tickets were issued by us. Contact us to change them."
            )
        if event.starts_at <= now:
            return RefundQuote(False, 0, 0, "The event has already started.")

        policy = await self.effective_policy(event) or {}
        tiers = policy.get("tiers") if isinstance(policy, dict) else None
        if not tiers:
            return RefundQuote(
                False,
                0,
                0,
                "This event has no self-service cancellation policy configured. Contact support.",
            )

        hours_before = (event.starts_at - now).total_seconds() / 3600.0
        percent = self._percent_for(tiers, hours_before)
        if percent <= 0:
            return RefundQuote(False, 0, 0, "The cancellation deadline for this event has passed.")

        refundable = booking.total_paise - booking.refunded_paise
        amount = min(percentage_of(booking.total_paise, Decimal(percent)), refundable)
        if amount <= 0:
            return RefundQuote(False, 0, percent, "Nothing left to refund.")
        return RefundQuote(True, amount, percent, f"{percent}% refund")

    @staticmethod
    def _percent_for(tiers: Sequence[dict[str, Any]], hours_before: float) -> int:
        """Pick the tier the booking qualifies for.

        Tiers are "at least N hours before the event → P percent". The most
        generous qualifying tier wins, which is the reading a customer would
        expect and the one that cannot be argued with.
        """
        best = 0
        for tier in tiers:
            try:
                threshold = float(tier["hours_before"])
                percent = int(tier["percent"])
            except (KeyError, TypeError, ValueError):
                continue
            if hours_before >= threshold:
                best = max(best, percent)
        return best

    # ---------------------------------------------------------- requests ---

    async def request_refund(
        self,
        *,
        booking: Booking,
        payment: Payment | None = None,
        amount_paise: int | None = None,
        reason: RefundReason,
        actor: User | None,
        note: str | None = None,
    ) -> Refund:
        """Record a refund request. Does not move money.

        The provider call happens in the worker, so a slow or failing gateway
        never blocks the request that triggered it.
        """
        payment = payment or await self.payments.captured_for_booking(booking.id)
        if payment is None:
            raise BusinessRuleError(
                "No captured payment exists for this booking.",
                code="NO_CAPTURED_PAYMENT",
            )
        if payment.status not in (PaymentStatus.CAPTURED, PaymentStatus.PARTIALLY_REFUNDED):
            raise BusinessRuleError(
                "This payment cannot be refunded in its current state.",
                code="PAYMENT_NOT_REFUNDABLE",
            )

        if await self.refunds.has_open_request(booking.id):
            raise ConflictError(
                "A refund is already in progress for this booking.",
                code="REFUND_IN_PROGRESS",
            )

        already = await self.refunds.succeeded_total(booking.id)
        remaining = booking.total_paise - already
        amount = amount_paise if amount_paise is not None else remaining

        if amount <= 0:
            raise BusinessRuleError(
                "This booking has already been fully refunded.",
                code="ALREADY_REFUNDED",
            )
        if amount > remaining:
            # The database constraint would reject it anyway; failing here
            # gives the operator a usable message.
            raise BusinessRuleError(
                f"Refund exceeds the refundable balance of {remaining} paise.",
                code="REFUND_EXCEEDS_BALANCE",
                details={"remaining_paise": remaining},
            )

        refund = Refund(
            booking_id=booking.id,
            payment_id=payment.id,
            amount_paise=amount,
            currency=booking.currency,
            status=RefundStatus.REQUESTED,
            reason=reason,
            reason_note=note,
            provider=payment.provider,
            idempotency_key=f"refund:{booking.id}:{already + amount}",
            requested_by_id=actor.id if actor else None,
        )
        self.refunds.add(refund)
        await self.session.flush()

        await self.audit.record(
            "refund.requested",
            entity_type="refund",
            entity_id=refund.id,
            actor=actor,
            after={
                "booking_id": str(booking.id),
                "amount_paise": amount,
                "reason": reason.value,
            },
        )
        await self.outbox.enqueue(
            topic=TOPIC_REFUND_PROCESS,
            payload={"refund_id": str(refund.id)},
            dedup_key=f"refund.process:{refund.id}",
        )
        await self.session.commit()

        logger.info(
            "refund_requested",
            refund_id=str(refund.id),
            booking_id=str(booking.id),
            amount_paise=amount,
        )
        return refund

    async def cancel_booking(
        self, *, booking: Booking, event: Event, actor: User, customer_initiated: bool
    ) -> Refund | None:
        """Cancel a booking and start the refund it is entitled to."""
        if booking.status is BookingStatus.CANCELLED:
            raise BusinessRuleError("This booking is already cancelled.", code="ALREADY_CANCELLED")

        if customer_initiated:
            quote = await self.quote(booking=booking, event=event)
            if not quote.eligible:
                raise BusinessRuleError(quote.reason, code="REFUND_NOT_ELIGIBLE")
            amount: int | None = quote.amount_paise
            reason = RefundReason.CUSTOMER_CANCELLED
        else:
            amount = None  # full remaining balance
            reason = RefundReason.ADMIN_CANCELLED

        refund = None
        payment = await self.payments.captured_for_booking(booking.id)
        if payment is not None:
            refund = await self.request_refund(
                booking=booking,
                payment=payment,
                amount_paise=amount,
                reason=reason,
                actor=actor,
            )

        # Seats a confirmed booking was holding go back on sale: the tickets are void now, so
        # leaving them counted as sold would hide seats that nobody can use.
        was_sold = booking.status in (BookingStatus.CONFIRMED, BookingStatus.PARTIALLY_REFUNDED)
        booking.status = BookingStatus.CANCELLED
        booking.cancelled_at = datetime.now(UTC)
        booking.cancellation_reason = reason.value
        if was_sold:
            for item in await self.bookings.items(booking.id):
                await self.inventory.return_sold(item.ticket_category_id, item.quantity)

        # Tickets are void from the moment the booking is cancelled — waiting
        # for the money to settle would let someone walk in on a cancelled
        # ticket.
        await self.tickets.invalidate_for_booking(
            booking.id, status=TicketStatus.CANCELLED, now=datetime.now(UTC)
        )
        await self.outbox.enqueue(
            topic=TOPIC_BOOKING_CANCELLED,
            payload={"booking_id": str(booking.id)},
            dedup_key=f"booking.cancelled:{booking.id}",
        )
        await self.session.commit()
        return refund

    # ------------------------------------------------------- settlement ---

    async def process_pending(self, refund_id: uuid.UUID) -> RefundStatus:
        """Send one refund to the provider. Called by the worker.

        The idempotency key means a retry after a timeout cannot refund twice:
        the provider returns the original refund rather than making a new one.
        """
        refund = await self.refunds.get(refund_id)
        if refund is None:
            raise NotFoundError("Refund not found.", code="REFUND_NOT_FOUND")
        if refund.status in (RefundStatus.SUCCEEDED, RefundStatus.FAILED):
            return refund.status

        payment = await self.payments.get(refund.payment_id)
        if payment is None or not payment.provider_payment_id:
            refund.status = RefundStatus.FAILED
            refund.failure_reason = "No provider payment id to refund against"
            await self.session.commit()
            return RefundStatus.FAILED

        refund.status = RefundStatus.PROCESSING
        refund.attempts += 1
        await self.session.commit()

        result = await self.provider.refund(
            provider_payment_id=payment.provider_payment_id,
            amount_paise=refund.amount_paise,
            idempotency_key=refund.idempotency_key,
        )

        refund.provider_refund_id = result.provider_refund_id
        if result.completed:
            await self._settle(refund, payment)
        else:
            # Accepted but not settled. Reconciliation will finish it.
            refund.failure_reason = result.failure_reason
            await self.session.commit()
        return refund.status

    async def _settle(self, refund: Refund, payment: Payment) -> None:
        """Apply a confirmed refund — the only place tickets become REFUNDED."""
        now = datetime.now(UTC)
        refund.status = RefundStatus.SUCCEEDED
        refund.completed_at = now

        booking = await self.bookings.get(refund.booking_id)
        if booking is not None:
            booking.refunded_paise += refund.amount_paise
            fully_refunded = booking.refunded_paise >= booking.total_paise
            booking.status = (
                BookingStatus.REFUNDED if fully_refunded else BookingStatus.PARTIALLY_REFUNDED
            )

            # Only a full refund voids the tickets. Refunds are not linked to
            # individual tickets yet, so voiding on a partial refund takes
            # away seats the customer has still paid for — refund one of four
            # and lose all four. Until ticket-level refunds exist, a partial
            # refund returns money and leaves admission intact.
            if fully_refunded:
                await self.tickets.invalidate_for_booking(
                    booking.id, status=TicketStatus.REFUNDED, now=now
                )
            else:
                logger.info(
                    "partial_refund_tickets_retained",
                    booking_id=str(booking.id),
                    refunded_paise=booking.refunded_paise,
                    total_paise=booking.total_paise,
                )

        payment.status = (
            PaymentStatus.REFUNDED
            if booking is not None and booking.refunded_paise >= booking.total_paise
            else PaymentStatus.PARTIALLY_REFUNDED
        )

        await self.outbox.enqueue(
            topic=TOPIC_REFUND_COMPLETED,
            payload={"refund_id": str(refund.id), "booking_id": str(refund.booking_id)},
            dedup_key=f"refund.completed:{refund.id}",
        )
        await self.session.commit()
        logger.info("refund_succeeded", refund_id=str(refund.id))

    async def reconcile_in_flight(self, *, limit: int = 50) -> int:
        """Re-check refunds the provider has not confirmed yet.

        Settlement takes days at some banks, so "requested" is not a terminal
        state and nothing downstream may treat it as one.
        """
        pending = await self.refunds.in_flight(limit=limit)
        updated = 0
        for refund in pending:
            # Captured before the attempt: a rollback expires the object, and
            # reading its id in the error handler would raise MissingGreenlet
            # and abandon the rest of the batch.
            refund_id = refund.id
            try:
                status = await self.process_pending(refund_id)
                if status is RefundStatus.SUCCEEDED:
                    updated += 1
            except Exception as exc:
                await self.session.rollback()
                logger.warning(
                    "refund_reconciliation_failed",
                    refund_id=str(refund_id),
                    error=str(exc),
                )
        return updated

    async def refund_event_bookings(self, *, event: Event, limit: int = 50) -> int:
        """Refund one batch of confirmed bookings for a cancelled event.

        Batched because a sold-out event is thousands of bookings and each
        refund is a provider call. The caller re-enqueues until this returns
        zero, so a worker restart resumes instead of starting over.

        Event cancellation is the company's fault, so it is always a **full**
        refund — the per-event cancellation tiers do not apply.
        """
        from app.core.pagination import PageParams

        bookings, _ = await self.bookings.list_admin(
            PageParams(page=1, size=limit),
            event_id=event.id,
            status=BookingStatus.CONFIRMED,
        )
        processed = 0
        for booking in bookings:
            try:
                payment = await self.payments.captured_for_booking(booking.id)
                if payment is not None and not await self.refunds.has_open_request(booking.id):
                    await self.request_refund(
                        booking=booking,
                        payment=payment,
                        amount_paise=None,
                        reason=RefundReason.EVENT_CANCELLED,
                        actor=None,
                        note=f"Event cancelled: {event.cancellation_reason or ''}".strip(),
                    )
                booking.status = BookingStatus.CANCELLED
                booking.cancelled_at = datetime.now(UTC)
                booking.cancellation_reason = RefundReason.EVENT_CANCELLED.value
                await self.tickets.invalidate_for_booking(
                    booking.id, status=TicketStatus.CANCELLED, now=datetime.now(UTC)
                )
                await self.session.commit()
                processed += 1
            except Exception as exc:
                await self.session.rollback()
                logger.warning(
                    "event_cancellation_refund_failed",
                    booking_id=str(booking.id),
                    error=str(exc),
                )
        return processed

    async def for_booking(self, booking_id: uuid.UUID) -> Sequence[Refund]:
        return await self.refunds.for_booking(booking_id)
