"""Payment confirmation — one path for every route into it.

Checkout verification and signed webhooks both end up in
`confirm_from_provider`. Having a single place where a payment becomes
"confirmed" is what makes the duplicate cases safe: whichever arrives first
confirms the booking, and the other is a no-op.

Three rules this module exists to enforce:

* a browser saying "payment succeeded" is never evidence — the provider is
  always asked, or the webhook signature verified;
* a provider payment ID appears at most once, enforced by a unique index;
* a webhook event ID is processed at most once, likewise.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AuthenticationError, BusinessRuleError, NotFoundError
from app.models.commerce import (
    Booking,
    BookingStatus,
    Payment,
    PaymentStatus,
    PaymentWebhookEvent,
    RefundReason,
)
from app.models.user import User
from app.repositories.commerce import (
    BookingRepository,
    PaymentRepository,
    WebhookEventRepository,
)
from app.services.audit import AuditService
from app.services.booking import BookingService
from app.services.payment_provider import (
    CheckoutOrder,
    PaymentProvider,
    VerifiedPayment,
    WebhookEnvelope,
)
from app.services.refund import RefundService

logger = structlog.get_logger(__name__)


class PaymentService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        provider: PaymentProvider,
        bookings: BookingService,
        refunds: RefundService,
    ) -> None:
        self.session = session
        self.settings = settings
        self.provider = provider
        self.booking_service = bookings
        self.refund_service = refunds
        self.payments = PaymentRepository(session)
        self.bookings = BookingRepository(session)
        self.webhooks = WebhookEventRepository(session)
        self.audit = AuditService(session)

    # ------------------------------------------------------- checkout ---

    async def start_checkout(self, booking: Booking, *, customer: User) -> CheckoutOrder:
        """Create (or re-use) the provider order for a pending booking.

        Re-use matters: a customer who closes the payment sheet and reopens it
        must land on the same order, not a second charge.
        """
        if booking.user_id != customer.id:
            raise NotFoundError("Booking not found.", code="BOOKING_NOT_FOUND")
        if booking.status is BookingStatus.CONFIRMED:
            raise BusinessRuleError(
                "This booking is already paid for.", code="BOOKING_ALREADY_CONFIRMED"
            )
        if booking.status is not BookingStatus.PENDING:
            raise BusinessRuleError(
                "This booking can no longer be paid for.", code="BOOKING_NOT_PAYABLE"
            )
        if booking.expires_at and booking.expires_at <= datetime.now(UTC):
            raise BusinessRuleError(
                "This booking has expired. Please select your tickets again.",
                code="BOOKING_EXPIRED",
            )

        idempotency_key = f"order:{booking.id}"
        existing = await self.payments.by_idempotency_key(idempotency_key)
        if existing is not None and existing.provider_order_id:
            return CheckoutOrder(
                provider=existing.provider,
                provider_order_id=existing.provider_order_id,
                amount_paise=existing.amount_paise,
                currency=existing.currency,
            )

        # Outside any inventory transaction, deliberately.
        order = await self.provider.create_order(
            amount_paise=booking.total_paise,
            currency=booking.currency,
            reference=booking.reference,
            idempotency_key=idempotency_key,
        )

        payment = existing or Payment(
            booking_id=booking.id,
            provider=self.provider.name,
            amount_paise=booking.total_paise,
            currency=booking.currency,
            idempotency_key=idempotency_key,
        )
        payment.provider_order_id = order.provider_order_id
        payment.status = PaymentStatus.PENDING
        if existing is None:
            self.payments.add(payment)
        await self.session.commit()
        return order

    # --------------------------------------------- the single confirm path ---

    async def confirm_from_provider(
        self, verified: VerifiedPayment, *, source: str
    ) -> Booking | None:
        """Apply a provider-verified payment result.

        Every route — checkout return and webhook — comes through here.
        Idempotent: a repeat for an already-captured payment returns the
        booking and changes nothing.
        """
        payment = await self._locate_payment(verified)
        if payment is None:
            logger.warning(
                "payment_not_found_for_provider_result",
                provider_payment_id=verified.provider_payment_id,
                source=source,
            )
            return None

        booking = await self.bookings.get(payment.booking_id)
        if booking is None:  # pragma: no cover - RESTRICT prevents this
            return None

        if payment.status is PaymentStatus.CAPTURED:
            return booking

        if verified.failed:
            await self._mark_failed(payment, verified)
            return booking

        if not verified.succeeded:
            # Authorized, or still in flight. The money is held but not taken,
            # so nothing is confirmed and nothing is refunded — the
            # reconciliation sweep asks again.
            payment.status = PaymentStatus.AUTHORIZED
            payment.provider_status = verified.provider_status
            if verified.provider_payment_id and not payment.provider_payment_id:
                payment.provider_payment_id = verified.provider_payment_id
            await self.session.commit()
            logger.info(
                "payment_pending_capture",
                payment_id=str(payment.id),
                provider_status=verified.provider_status,
            )
            return booking

        if verified.amount_paise != payment.amount_paise:
            # Short payment, or a payment pointed at the wrong booking. Never
            # confirm; a human has to look at it.
            logger.error(
                "payment_amount_mismatch",
                payment_id=str(payment.id),
                expected=payment.amount_paise,
                received=verified.amount_paise,
            )
            payment.status = PaymentStatus.FAILED
            payment.failure_reason = "amount_mismatch"
            payment.failed_at = datetime.now(UTC)
            await self.session.commit()
            raise BusinessRuleError(
                "Payment amount does not match the booking.",
                code="PAYMENT_AMOUNT_MISMATCH",
            )

        now = datetime.now(UTC)
        captured = await self.payments.mark_captured(
            payment.id,
            provider_payment_id=verified.provider_payment_id,
            now=now,
            method=verified.method,
        )
        if not captured:
            # Another request captured it first; that path confirms.
            await self.session.commit()
            return booking

        await self.session.commit()

        confirmed = await self.booking_service.confirm_paid(booking)
        if not confirmed and booking.status is not BookingStatus.CONFIRMED:
            # Paid, but the tickets are gone. Refund rather than keep money
            # for seats that cannot be honoured.
            logger.error(
                "payment_captured_without_inventory",
                booking_id=str(booking.id),
                payment_id=str(payment.id),
            )
            await self.refund_service.request_refund(
                booking=booking,
                payment=payment,
                amount_paise=payment.amount_paise,
                reason=RefundReason.INVENTORY_UNAVAILABLE,
                actor=None,
                note="Inventory unavailable after payment captured",
            )
        return booking

    async def verify_checkout(
        self,
        provider_payment_id: str,
        *,
        customer: User,
        provider_order_id: str | None = None,
        signature: str | None = None,
    ) -> Booking:
        """Confirm from the browser's return — by asking the provider.

        The redirect itself proves nothing; it is only a hint that a payment
        may exist. When the provider also hands the client a signature it is
        checked first — cheap, and it rejects a fabricated payment id before
        a network call is spent on it. The provider's own answer still
        decides.
        """
        if signature and provider_order_id:
            verify = getattr(self.provider, "verify_checkout_signature", None)
            if verify is not None and not verify(
                provider_order_id=provider_order_id,
                provider_payment_id=provider_payment_id,
                signature=signature,
            ):
                logger.warning(
                    "checkout_signature_invalid", provider_payment_id=provider_payment_id
                )
                raise AuthenticationError(
                    "Payment verification failed.", code="CHECKOUT_SIGNATURE_INVALID"
                )

        verified = await self.provider.fetch_payment(provider_payment_id)
        booking = await self.confirm_from_provider(verified, source="checkout")
        if booking is None:
            raise NotFoundError("Payment not found.", code="PAYMENT_NOT_FOUND")
        if booking.user_id != customer.id:
            raise NotFoundError("Booking not found.", code="BOOKING_NOT_FOUND")
        return booking

    # ------------------------------------------------------------ webhook ---

    async def handle_webhook(
        self, *, body: bytes, headers: dict[str, str], source_ip: str | None
    ) -> str:
        """Verify, record, then act — in that order.

        The event is recorded before it is acted on, so a crash mid-processing
        leaves evidence. The unique constraint on (provider, event id) is what
        makes a redelivered webhook a no-op rather than a second confirmation.
        """
        try:
            envelope: WebhookEnvelope = self.provider.parse_webhook(body=body, headers=headers)
        except AuthenticationError:
            logger.warning("webhook_signature_invalid", source_ip=source_ip)
            raise

        record = PaymentWebhookEvent(
            provider=self.provider.name,
            provider_event_id=envelope.provider_event_id,
            event_type=envelope.event_type,
            signature_verified=True,
            payload=envelope.payload,
            source_ip=source_ip,
        )
        self.webhooks.add(record)
        try:
            await self.session.commit()
        except IntegrityError:
            # Already handled. Providers retry; this is routine.
            await self.session.rollback()
            logger.info(
                "webhook_duplicate_ignored",
                provider_event_id=envelope.provider_event_id,
            )
            return "duplicate"

        if not envelope.provider_payment_id:
            await self._mark_webhook_processed(record.id)
            return "ignored"

        try:
            verified = VerifiedPayment(
                provider_payment_id=envelope.provider_payment_id,
                provider_order_id=envelope.provider_order_id or "",
                amount_paise=envelope.amount_paise or 0,
                currency="INR",
                state=envelope.state,
                provider_status=envelope.event_type,
            )
            await self.confirm_from_provider(verified, source="webhook")
        except Exception as exc:
            await self.session.rollback()
            await self._record_webhook_error(record.id, str(exc))
            raise

        await self._mark_webhook_processed(record.id)
        return "processed"

    async def _mark_webhook_processed(self, record_id: uuid.UUID) -> None:
        record = await self.webhooks.get(record_id)
        if record is not None:
            record.processed_at = datetime.now(UTC)
            await self.session.commit()

    async def _record_webhook_error(self, record_id: uuid.UUID, error: str) -> None:
        record = await self.webhooks.get(record_id)
        if record is not None:
            record.processing_error = error[:2000]
            await self.session.commit()

    # ----------------------------------------------------- reconciliation ---

    async def reconcile_in_flight(self, *, limit: int = 50) -> int:
        """Ask the provider about payments whose webhook never arrived.

        Webhooks get lost. Without this a customer is charged and holds no
        booking, and nothing in the system notices.
        """
        cutoff = datetime.now(UTC) - timedelta(
            seconds=self.settings.payment_reconcile_after_seconds
        )
        stale = await self.payments.stale_in_flight(older_than=cutoff, limit=limit)

        reconciled = 0
        for payment in stale:
            if not payment.provider_payment_id:
                continue
            try:
                verified = await self.provider.fetch_payment(payment.provider_payment_id)
                await self.confirm_from_provider(verified, source="reconciliation")
                payment.reconciled_at = datetime.now(UTC)
                await self.session.commit()
                reconciled += 1
            except Exception as exc:
                await self.session.rollback()
                logger.warning(
                    "payment_reconciliation_failed",
                    payment_id=str(payment.id),
                    error=str(exc),
                )
        return reconciled

    # ------------------------------------------------------------ helpers ---

    async def _locate_payment(self, verified: VerifiedPayment) -> Payment | None:
        payment = await self.payments.by_provider_payment_id(
            self.provider.name, verified.provider_payment_id
        )
        if payment is not None:
            return payment
        if verified.provider_order_id:
            return await self.payments.by_provider_order_id(
                self.provider.name, verified.provider_order_id
            )
        return None

    async def _mark_failed(self, payment: Payment, verified: VerifiedPayment) -> None:
        payment.status = PaymentStatus.FAILED
        payment.provider_status = verified.provider_status
        payment.failure_reason = verified.failure_reason
        payment.failed_at = datetime.now(UTC)
        await self.session.commit()
        logger.info("payment_failed", payment_id=str(payment.id))
