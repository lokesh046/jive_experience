"""Booking rules.

Transaction shape, which is the whole design:

    1. hold inventory + create booking   — one short transaction, committed
    2. create the provider order         — network call, no locks held
    3. confirm on verified payment       — one short transaction

Step 2 is outside a transaction on purpose. A gateway call takes hundreds of
milliseconds; holding an inventory row across it would cap the whole event at
a couple of sales per second.
"""

from __future__ import annotations

import secrets
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import BusinessRuleError, ConflictError, NotFoundError, PermissionDeniedError
from app.core.pagination import PageParams
from app.models.commerce import Booking, BookingItem, BookingStatus
from app.models.event import Event
from app.models.user import User, UserRole
from app.repositories.catalogue import EventRepository
from app.repositories.commerce import BookingRepository, PaymentRepository
from app.schemas.booking import BookingCreateRequest
from app.services.audit import AuditService
from app.services.inventory import InventoryService, RequestedItem
from app.services.outbox import TOPIC_BOOKING_CONFIRMED, OutboxService

logger = structlog.get_logger(__name__)

REFERENCE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
"""Unambiguous characters only — references get read aloud at a gate."""


def generate_reference() -> str:
    return "JIVE-" + "".join(secrets.choice(REFERENCE_ALPHABET) for _ in range(8))


class BookingService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        inventory: InventoryService,
        outbox: OutboxService,
    ) -> None:
        self.session = session
        self.settings = settings
        self.inventory = inventory
        self.outbox = outbox
        self.bookings = BookingRepository(session)
        self.payments = PaymentRepository(session)
        self.events = EventRepository(session)
        self.audit = AuditService(session)

    # ----------------------------------------------------------- create ---

    async def create(
        self, payload: BookingCreateRequest, *, customer: User
    ) -> tuple[Booking, bool]:
        """Hold inventory and open a pending booking.

        Returns `(booking, created)`. `created is False` means an existing
        booking was returned for a repeated idempotency key — a double-tapped
        Book button must not hold twice the tickets.
        """
        if payload.idempotency_key:
            existing = await self.bookings.by_idempotency_key(customer.id, payload.idempotency_key)
            if existing is not None:
                return existing, False

        event = await self.events.public_by_slug(payload.event_slug)
        if event is None:
            raise NotFoundError("Event not found.", code="EVENT_NOT_FOUND")

        self._assert_can_book(customer)

        now = datetime.now(UTC)
        held = await self.inventory.hold(
            event=event,
            user_id=customer.id,
            items=[
                RequestedItem(ticket_category_id=item.ticket_category_id, quantity=item.quantity)
                for item in payload.items
            ],
            now=now,
        )

        # Every amount is computed here from the prices the database just
        # gave us. A client-submitted total is never trusted.
        subtotal = sum(item.line_total_paise for item in held)
        quantity = sum(item.quantity for item in held)

        booking = Booking(
            reference=await self._unique_reference(),
            user_id=customer.id,
            event_id=event.id,
            status=BookingStatus.PENDING,
            subtotal_paise=subtotal,
            fees_paise=0,
            total_paise=subtotal,
            quantity=quantity,
            currency=self.settings.default_currency,
            idempotency_key=payload.idempotency_key,
            expires_at=now + timedelta(seconds=self.settings.reservation_hold_seconds),
            customer_note=payload.customer_note,
        )
        self.bookings.add(booking)
        await self.session.flush()

        for item in held:
            self.session.add(
                BookingItem(
                    booking_id=booking.id,
                    ticket_category_id=item.ticket_category.id,
                    category_name=item.ticket_category.name,
                    unit_price_paise=item.unit_price_paise,
                    quantity=item.quantity,
                    line_total_paise=item.line_total_paise,
                )
            )

        await self.inventory.attach_to_booking([item.reservation_id for item in held], booking.id)

        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            # Two requests with the same idempotency key raced; the unique
            # constraint caught the loser. Return the winner's booking.
            if payload.idempotency_key:
                existing = await self.bookings.by_idempotency_key(
                    customer.id, payload.idempotency_key
                )
                if existing is not None:
                    return existing, False
            raise ConflictError(
                "That booking could not be created. Please try again.",
                code="BOOKING_CONFLICT",
            ) from exc

        # The items were added to the session directly, so this booking's
        # `items` collection has never been loaded. Serialising the response
        # would otherwise trigger a lazy load outside the async context and
        # fail with MissingGreenlet. One query here, deliberately, rather than
        # an exception at the edge.
        await self.session.refresh(booking, attribute_names=["items"])

        logger.info(
            "booking_created",
            booking_id=str(booking.id),
            reference=booking.reference,
            quantity=quantity,
            total_paise=subtotal,
        )
        return booking, True

    async def _unique_reference(self) -> str:
        for _ in range(8):
            candidate = generate_reference()
            if not await self.bookings.reference_taken(candidate):
                return candidate
        # 32^8 keyspace; eight collisions means something is badly wrong.
        raise ConflictError("Could not allocate a booking reference.", code="REFERENCE_EXHAUSTED")

    @staticmethod
    def _assert_can_book(customer: User) -> None:
        if customer.role is not UserRole.CUSTOMER:
            raise PermissionDeniedError(
                "Only customer accounts can book tickets.", code="NOT_A_CUSTOMER"
            )
        # A verified phone number is the control that makes the per-event
        # purchase limit mean anything, now that sign-in is a free Google
        # account. See docs/anti-bot.md.
        if not customer.phone_e164:
            raise BusinessRuleError(
                "Add a phone number to your account before booking.",
                code="PHONE_NUMBER_REQUIRED",
            )

    # ---------------------------------------------------------- confirm ---

    async def confirm_paid(self, booking: Booking) -> bool:
        """Confirm a booking whose payment is verified.

        Returns False when it was already confirmed — both the browser
        redirect and the webhook call this, and exactly one must win.

        The outbox row is written in **this** transaction: the work to issue
        tickets exists if and only if the booking is confirmed.
        """
        now = datetime.now(UTC)

        if not await self.inventory.commit_for_booking(booking.id):
            # The hold expired before the money landed. Try to take the stock
            # again; if it is genuinely gone the caller refunds.
            if not await self.inventory.reacquire_for_booking(booking.id):
                logger.warning(
                    "booking_inventory_unavailable_after_payment",
                    booking_id=str(booking.id),
                )
                return False
            if not await self.inventory.commit_for_booking(booking.id):
                return False

        if not await self.bookings.confirm(booking.id, now=now):
            return False

        await self.outbox.enqueue(
            topic=TOPIC_BOOKING_CONFIRMED,
            payload={"booking_id": str(booking.id), "reference": booking.reference},
            dedup_key=f"booking.confirmed:{booking.id}",
        )
        await self.session.commit()

        logger.info("booking_confirmed", booking_id=str(booking.id))
        return True

    async def expire(self, booking: Booking) -> None:
        """Abandon a pending booking and return its tickets to sale."""
        await self.inventory.release_for_booking(booking.id)
        booking.status = BookingStatus.EXPIRED
        booking.cancelled_at = datetime.now(UTC)
        await self.session.commit()

    async def sweep_expired(self, *, limit: int = 200) -> int:
        """Expire pending bookings whose hold has run out.

        Runs in the worker alongside the reservation sweep. Claiming rows with
        SKIP LOCKED makes it safe to run several workers.
        """
        now = datetime.now(UTC)
        expired = await self.bookings.claim_expired(now=now, limit=limit)
        for booking in expired:
            await self.inventory.release_for_booking(booking.id)
        if expired:
            await self.session.commit()
            logger.info("bookings_expired", count=len(expired))
        return len(expired)

    # ------------------------------------------------------------ reads ---

    async def for_customer(
        self, customer: User, params: PageParams
    ) -> tuple[Sequence[Booking], int]:
        return await self.bookings.list_for_user(customer.id, params)

    async def get_for_customer(self, reference: str, customer: User) -> Booking:
        booking = await self.bookings.by_reference(reference)
        if booking is None or booking.user_id != customer.id:
            # Same answer either way: a wrong owner must not be able to learn
            # that a reference exists.
            raise NotFoundError("Booking not found.", code="BOOKING_NOT_FOUND")
        return booking

    async def get_admin(self, booking_id: uuid.UUID) -> Booking:
        booking = await self.bookings.get(booking_id)
        if booking is None:
            raise NotFoundError("Booking not found.", code="BOOKING_NOT_FOUND")
        return booking

    async def list_admin(
        self,
        params: PageParams,
        *,
        event_id: uuid.UUID | None = None,
        status: BookingStatus | None = None,
        reference: str | None = None,
    ) -> tuple[Sequence[Booking], int]:
        return await self.bookings.list_admin(
            params, event_id=event_id, status=status, reference=reference
        )

    async def event_for(self, booking: Booking) -> Event:
        event = await self.events.get(booking.event_id)
        if event is None:  # pragma: no cover - RESTRICT makes this unreachable
            raise NotFoundError("Event not found.", code="EVENT_NOT_FOUND")
        return event
