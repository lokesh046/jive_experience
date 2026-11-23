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
from app.models.commerce import Booking, BookingItem, BookingSource, BookingStatus
from app.models.event import Event, EventStatus, TicketCategory
from app.models.user import User, UserRole, UserStatus
from app.repositories.catalogue import EventRepository, TicketCategoryRepository
from app.repositories.commerce import BookingRepository, PaymentRepository
from app.repositories.user import UserRepository
from app.schemas.booking import BookingCreateRequest, BoxOfficeSaleRequest, ManualTicketRequest
from app.schemas.promo import PromoCheckOut, PromoCheckRequest
from app.services.audit import AuditService
from app.services.inventory import InventoryService, RequestedItem
from app.services.outbox import TOPIC_BOOKING_CONFIRMED, OutboxService
from app.services.promo import PromoService

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
        self.promos = PromoService(session)

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

        # Take the per-customer lock *before* deciding anything, then look the
        # key up again inside it.
        #
        # The check above races: two submissions of the same key both find
        # nothing, and the loser then reaches the purchase-limit check, which
        # now counts the winner's booking and refuses with
        # PURCHASE_LIMIT_EXCEEDED — the opposite of what an idempotent retry
        # should do. Re-reading inside the critical section returns the
        # winner's booking instead.
        if payload.idempotency_key:
            await self.inventory.lock_customer_event(customer.id, event.id)
            existing = await self.bookings.by_idempotency_key(customer.id, payload.idempotency_key)
            if existing is not None:
                return existing, False

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

        discount = 0
        promo_id: uuid.UUID | None = None
        if payload.promo_code:
            # One customer's attempts are serialised, so two parallel requests cannot both
            # pass a "once per customer" limit.
            await self.inventory.lock_customer_event(customer.id, event.id)
            try:
                applied = await self.promos.redeem(
                    payload.promo_code, event=event, customer=customer, subtotal_paise=subtotal
                )
            except Exception:
                # The booking will not exist, so the tickets just held must not stay held.
                await self.inventory.release_held(held)
                raise
            discount, promo_id = applied.discount_paise, applied.promo.id

        booking = Booking(
            reference=await self._unique_reference(),
            user_id=customer.id,
            event_id=event.id,
            status=BookingStatus.PENDING,
            subtotal_paise=subtotal,
            fees_paise=0,
            discount_paise=discount,
            promo_code_id=promo_id,
            total_paise=subtotal - discount,
            quantity=quantity,
            currency=self.settings.default_currency,
            idempotency_key=payload.idempotency_key,
            expires_at=now + timedelta(seconds=self.settings.reservation_hold_seconds),
            customer_note=payload.customer_note,
        )
        # Read before anything can roll back: SQLAlchemy expires loaded
        # objects on rollback, so re-reading `customer.id` afterwards would
        # trigger a lazy refresh outside the async context.
        customer_id = customer.id

        try:
            # Everything that can violate a constraint belongs inside this
            # block. The unique key on (user_id, idempotency_key) is enforced
            # on the INSERT — at flush, not at commit — so a flush outside
            # the handler turns a racing retry into a 500 instead of
            # returning the booking that won.
            self.bookings.add(booking)
            await self.session.flush()

            # Only now does `booking.id` exist: it is a server default, so it
            # is populated by the flush above. Building the items before that
            # gives every one of them a NULL foreign key.
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

            await self.inventory.attach_to_booking(
                [item.reservation_id for item in held], booking.id
            )
            await self.session.commit()
        except IntegrityError as exc:
            logger.info("booking_integrity_conflict", detail=str(exc.orig)[:200])
            await self.session.rollback()
            # Two requests with the same idempotency key raced; the unique
            # constraint caught the loser. Return the winner's booking.
            if payload.idempotency_key:
                existing = await self.bookings.by_idempotency_key(
                    customer_id, payload.idempotency_key
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

        if booking.total_paise == 0:
            # A code that covers the whole price: there is nothing to pay, so confirm now. The
            # gateway cannot take a zero-amount payment, and the customer should not be sent
            # to one.
            await self.confirm_paid(booking)
            await self.session.refresh(
                booking, attribute_names=["status", "confirmed_at", "expires_at"]
            )

        logger.info(
            "booking_created",
            booking_id=str(booking.id),
            reference=booking.reference,
            quantity=quantity,
            discount_paise=discount,
            total_paise=booking.total_paise,
        )
        return booking, True

    async def preview_promo(self, payload: PromoCheckRequest, *, customer: User) -> PromoCheckOut:
        """What a code would take off these tickets, without holding anything.

        Prices come from the database; the client only says which tickets and how many.
        """
        event = await self.events.public_by_slug(payload.event_slug)
        if event is None:
            raise NotFoundError("Event not found.", code="EVENT_NOT_FOUND")
        prices = {c.id: c.price_paise for c in event.ticket_categories if c.is_active}
        subtotal = 0
        for item in payload.items:
            if item.ticket_category_id not in prices:
                raise NotFoundError(
                    "Ticket category not found for this event.", code="CATEGORY_NOT_FOUND"
                )
            subtotal += prices[item.ticket_category_id] * item.quantity
        applied = await self.promos.evaluate(
            payload.code, event=event, customer=customer, subtotal_paise=subtotal
        )
        return PromoCheckOut(
            code=applied.promo.code,
            subtotal_paise=subtotal,
            discount_paise=applied.discount_paise,
            total_paise=subtotal - applied.discount_paise,
            description=applied.promo.description,
        )

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

    # ------------------------------------------------------ hand-issued ---

    async def issue_manually(
        self, event_id: uuid.UUID, payload: ManualTicketRequest, *, actor: User
    ) -> Booking:
        """Issue tickets without checkout: free (complimentary) or paid in cash.

        The booking is confirmed on the spot and goes through the same outbox
        path as a paid one, so the worker issues the QR tickets and emails them
        to the recipient. Capacity is taken with the same guarded update an
        online sale uses. A cash booking records the price as revenue; neither
        kind has a gateway payment, so there is nothing to refund through one.
        """
        event = await self.events.get(event_id)
        if event is None:
            raise NotFoundError("Event not found.", code="EVENT_NOT_FOUND")
        if event.status not in (EventStatus.PUBLISHED, EventStatus.SOLD_OUT):
            raise BusinessRuleError(
                "Tickets can only be issued for a published event.", code="EVENT_NOT_SELLABLE"
            )
        category = await TicketCategoryRepository(self.session).get(payload.ticket_category_id)
        if category is None or category.event_id != event.id:
            raise NotFoundError(
                "Ticket category not found for this event.", code="CATEGORY_NOT_FOUND"
            )

        users = UserRepository(self.session)
        email = str(payload.email).lower()
        recipient = await users.by_email(email)
        if recipient is None:
            # A customer row with no Google identity yet. When this person signs in with
            # Google under this email, the existing row is linked and they see their tickets.
            recipient = User(
                role=UserRole.CUSTOMER,
                status=UserStatus.ACTIVE,
                email=email,
                full_name=payload.full_name,
            )
            self.session.add(recipient)
            await self.session.flush()
        elif recipient.status is not UserStatus.ACTIVE:
            raise BusinessRuleError(
                "That account is suspended, so tickets cannot be issued to it.",
                code="ACCOUNT_NOT_ACTIVE",
            )
        recipient_id = recipient.id

        return await self._record_direct_sale(
            event=event,
            category=category,
            recipient_id=recipient_id,
            quantity=payload.quantity,
            kind=payload.kind,
            note=payload.note,
            actor=actor,
        )

    async def _record_direct_sale(
        self,
        *,
        event: Event,
        category: TicketCategory,
        recipient_id: uuid.UUID,
        quantity: int,
        kind: BookingSource,
        note: str | None,
        actor: User,
    ) -> Booking:
        """Take stock and confirm a booking that needs no gateway: free, or cash in hand."""
        await self.inventory.sell_directly(category, quantity)

        unit = category.price_paise if kind is BookingSource.CASH else 0
        total = unit * quantity
        now = datetime.now(UTC)
        booking = Booking(
            reference=await self._unique_reference(),
            user_id=recipient_id,
            event_id=event.id,
            status=BookingStatus.CONFIRMED,
            subtotal_paise=total,
            fees_paise=0,
            total_paise=total,
            quantity=quantity,
            currency=self.settings.default_currency,
            confirmed_at=now,
            customer_note=note,
            source=kind,
            issued_by_id=actor.id,
        )
        self.bookings.add(booking)
        await self.session.flush()
        self.session.add(
            BookingItem(
                booking_id=booking.id,
                ticket_category_id=category.id,
                category_name=category.name,
                unit_price_paise=unit,
                quantity=quantity,
                line_total_paise=total,
            )
        )
        await self.session.flush()
        await self.outbox.enqueue(
            topic=TOPIC_BOOKING_CONFIRMED,
            payload={"booking_id": str(booking.id), "reference": booking.reference},
            dedup_key=f"booking.confirmed:{booking.id}",
        )
        await self.audit.record(
            "booking.issued_manually",
            entity_type="booking",
            entity_id=booking.id,
            actor=actor,
            after={
                "kind": kind.value,
                "event_id": str(event.id),
                "category": category.name,
                "quantity": quantity,
                "total_paise": total,
                "recipient_id": str(recipient_id),
            },
        )
        await self.session.commit()
        await self.session.refresh(booking, attribute_names=["items"])
        logger.info(
            "booking_issued_manually",
            reference=booking.reference,
            kind=kind.value,
            quantity=quantity,
        )
        return booking

    # ------------------------------------------------------- box office ---

    async def box_office_sale(
        self, event_id: uuid.UUID, payload: BoxOfficeSaleRequest, *, actor: User
    ) -> Booking:
        """A walk-up sale at the counter, paid in cash or through the gateway.

        Cash is confirmed on the spot. Online takes the same inventory hold an
        online customer gets and leaves the booking pending: the seller then opens
        the gateway for the buyer, and the booking is confirmed only by the verified
        payment, exactly as on the website.
        """
        event = await self.events.get(event_id)
        if event is None:
            raise NotFoundError("Event not found.", code="EVENT_NOT_FOUND")
        if event.status not in (EventStatus.PUBLISHED, EventStatus.SOLD_OUT):
            raise BusinessRuleError(
                "Tickets can only be sold for a published event.", code="EVENT_NOT_SELLABLE"
            )
        category = await TicketCategoryRepository(self.session).get(payload.ticket_category_id)
        if category is None or category.event_id != event.id or not category.is_active:
            raise NotFoundError(
                "Ticket category not found for this event.", code="CATEGORY_NOT_FOUND"
            )

        buyer = await self._walk_in_buyer(payload)
        buyer_id = buyer.id
        note = " | ".join(
            part
            for part in (
                f"Box office: {payload.buyer_name}" if payload.buyer_name else "Box office",
                payload.buyer_phone,
                payload.note,
            )
            if part
        )

        if payload.method is BookingSource.CASH:
            return await self._record_direct_sale(
                event=event,
                category=category,
                recipient_id=buyer_id,
                quantity=payload.quantity,
                kind=BookingSource.CASH,
                note=note,
                actor=actor,
            )

        now = datetime.now(UTC)
        held = await self.inventory.hold(
            event=event,
            user_id=buyer_id,
            items=[RequestedItem(ticket_category_id=category.id, quantity=payload.quantity)],
            now=now,
        )
        total = sum(item.line_total_paise for item in held)
        booking = Booking(
            reference=await self._unique_reference(),
            user_id=buyer_id,
            event_id=event.id,
            status=BookingStatus.PENDING,
            subtotal_paise=total,
            fees_paise=0,
            total_paise=total,
            quantity=payload.quantity,
            currency=self.settings.default_currency,
            expires_at=now + timedelta(seconds=self.settings.reservation_hold_seconds),
            customer_note=note,
            source=BookingSource.ONLINE,
            issued_by_id=actor.id,
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
        await self.audit.record(
            "booking.box_office_started",
            entity_type="booking",
            entity_id=booking.id,
            actor=actor,
            after={"event_id": str(event.id), "quantity": payload.quantity, "total_paise": total},
        )
        await self.session.commit()
        await self.session.refresh(booking, attribute_names=["items"])
        if booking.total_paise == 0:
            await self.confirm_paid(booking)
            await self.session.refresh(
                booking, attribute_names=["status", "confirmed_at", "expires_at"]
            )
        return booking

    async def _walk_in_buyer(self, payload: BoxOfficeSaleRequest) -> User:
        """The account a counter sale belongs to.

        With an email, the buyer's real account (created if new) so the ticket also
        reaches their inbox. Without one, a throwaway account on an address that can
        never receive mail: nobody signs in to it and nothing is sent to it.
        """
        users = UserRepository(self.session)
        if payload.buyer_email:
            email = str(payload.buyer_email).lower()
            existing = await users.by_email(email)
            if existing is not None:
                if existing.status is not UserStatus.ACTIVE:
                    raise BusinessRuleError(
                        "That account is suspended, so tickets cannot be sold to it.",
                        code="ACCOUNT_NOT_ACTIVE",
                    )
                return existing
        else:
            email = f"walkin-{secrets.token_hex(8)}@walk-in.invalid"
        buyer = User(
            role=UserRole.CUSTOMER,
            status=UserStatus.ACTIVE,
            email=email,
            full_name=payload.buyer_name,
        )
        self.session.add(buyer)
        await self.session.flush()
        return buyer

    async def get_for_seller(self, reference: str, actor: User) -> Booking:
        """A counter booking, for the person who made it (or an administrator)."""
        booking = await self.bookings.by_reference(reference)
        if (
            booking is None
            or booking.issued_by_id is None
            or (actor.role is not UserRole.ADMIN and booking.issued_by_id != actor.id)
        ):
            raise NotFoundError("Booking not found.", code="BOOKING_NOT_FOUND")
        return booking

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
        await self.promos.release(booking.promo_code_id)
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
            await self.promos.release(booking.promo_code_id)
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
