"""Promo codes: checking a code, taking a use, and the admin side.

Rules that matter for money:

* the discount is worked out here, from the prices the database holds, never taken
  from the client;
* it can never exceed the subtotal, so a total can never go below zero;
* a limited code's uses are counted with one guarded UPDATE, so "first 100 buyers"
  holds under a rush, and a booking that lapses unpaid gives its use back;
* repeated wrong guesses are throttled, so codes cannot be brute-forced.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError, RateLimitedError
from app.core.money import percentage_of
from app.core.pagination import PageParams
from app.core.redis import get_redis
from app.models.event import Event
from app.models.promo import PromoCode, PromoDiscountType
from app.models.user import User
from app.repositories.promo import PromoRepository
from app.schemas.promo import PromoCreate, PromoUpdate, normalise_code
from app.services.audit import AuditService

logger = structlog.get_logger(__name__)

MAX_WRONG_GUESSES = 10
GUESS_WINDOW_SECONDS = 15 * 60


class PromoRejectedError(ConflictError):
    """The code cannot be used for this booking. The message says why, in plain words."""

    status_code = 422


@dataclass(frozen=True, slots=True)
class Applied:
    promo: PromoCode
    discount_paise: int


class PromoService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.promos = PromoRepository(session)
        self.audit = AuditService(session)

    # ----------------------------------------------------------- checking ---

    async def _throttle(self, user_id: uuid.UUID) -> None:
        """Count a wrong guess; refuse once someone has made too many."""
        try:
            redis = get_redis()
            key = f"promo:wrong:{user_id}"
            count = await redis.incr(key)
            if count == 1:
                await redis.expire(key, GUESS_WINDOW_SECONDS)
            if count > MAX_WRONG_GUESSES:
                raise RateLimitedError("Too many tries. Please wait a few minutes.")
        except RateLimitedError:
            raise
        except Exception:  # Redis trouble must not stop a customer who has a valid code
            logger.warning("promo_throttle_unavailable")

    async def _refuse(self, user_id: uuid.UUID, code: str, message: str) -> PromoRejectedError:
        await self._throttle(user_id)
        return PromoRejectedError(message, code=code)

    async def evaluate(
        self, raw_code: str, *, event: Event, customer: User, subtotal_paise: int
    ) -> Applied:
        """Everything that decides whether, and by how much, a code applies. Takes no use."""
        promo = await self.promos.by_code(normalise_code(raw_code))
        now = datetime.now(UTC)
        if promo is None or not promo.is_active:
            raise await self._refuse(customer.id, "PROMO_INVALID", "That code is not valid.")
        if promo.event_id is not None and promo.event_id != event.id:
            raise await self._refuse(
                customer.id, "PROMO_WRONG_EVENT", "That code is not valid for this event."
            )
        if promo.valid_from is not None and now < promo.valid_from:
            raise await self._refuse(
                customer.id, "PROMO_NOT_STARTED", "That code is not active yet."
            )
        if promo.valid_until is not None and now > promo.valid_until:
            raise await self._refuse(customer.id, "PROMO_EXPIRED", "That code has expired.")
        if promo.max_uses_per_customer is not None:
            used = await self.promos.uses_by_customer(promo.id, customer.id)
            if used >= promo.max_uses_per_customer:
                raise PromoRejectedError(
                    "You have already used that code.", code="PROMO_ALREADY_USED"
                )

        if promo.max_uses is not None and promo.used_count >= promo.max_uses:
            raise await self._refuse(
                customer.id, "PROMO_EXHAUSTED", "That code has been fully used."
            )
        if promo.discount_type is PromoDiscountType.PERCENT:
            discount = percentage_of(subtotal_paise, Decimal(promo.percent_off or 0))
        else:
            discount = promo.amount_off_paise or 0
        discount = max(0, min(discount, subtotal_paise))
        return Applied(promo=promo, discount_paise=discount)

    async def redeem(
        self, raw_code: str, *, event: Event, customer: User, subtotal_paise: int
    ) -> Applied:
        """Check the code and count the use, inside the caller's transaction.

        If the booking later fails, the transaction rolls back and the use with it.
        """
        applied = await self.evaluate(
            raw_code, event=event, customer=customer, subtotal_paise=subtotal_paise
        )
        if not await self.promos.take_use(applied.promo.id):
            raise PromoRejectedError("That code has been fully used.", code="PROMO_EXHAUSTED")
        return applied

    async def release(self, promo_id: uuid.UUID | None) -> None:
        """A booking that lapsed unpaid gives its use back."""
        if promo_id is not None:
            await self.promos.give_back_use(promo_id)

    # -------------------------------------------------------------- admin ---

    async def list_codes(self, params: PageParams) -> tuple[list[PromoCode], int]:
        rows, total = await self.promos.page(params)
        return list(rows), total

    async def create(self, payload: PromoCreate, *, actor: User) -> PromoCode:
        if await self.promos.by_code(payload.code):
            raise ConflictError("That code already exists.", code="PROMO_CODE_TAKEN")
        promo = PromoCode(**payload.model_dump(), created_by_id=actor.id)
        self.promos.add(promo)
        await self.session.flush()
        await self.audit.record(
            "promo.created",
            entity_type="promo_code",
            entity_id=promo.id,
            actor=actor,
            after={
                "code": promo.code,
                "type": promo.discount_type.value,
                "percent_off": promo.percent_off,
                "amount_off_paise": promo.amount_off_paise,
                "event_id": str(promo.event_id) if promo.event_id else None,
                "max_uses": promo.max_uses,
            },
        )
        await self.session.commit()
        return promo

    async def update(self, promo_id: uuid.UUID, payload: PromoUpdate, *, actor: User) -> PromoCode:
        promo = await self.promos.get(promo_id)
        if promo is None:
            raise NotFoundError("Promo code not found.", code="PROMO_NOT_FOUND")
        changes = payload.model_dump(exclude_unset=True)
        if changes.get("max_uses") is not None and changes["max_uses"] < promo.used_count:
            raise ConflictError(
                f"{promo.used_count} uses are already counted, so the limit cannot be lower.",
                code="PROMO_LIMIT_BELOW_USED",
            )
        before = {"is_active": promo.is_active, "max_uses": promo.max_uses}
        for field, value in changes.items():
            setattr(promo, field, value)
        if (
            promo.valid_from is not None
            and promo.valid_until is not None
            and promo.valid_until <= promo.valid_from
        ):
            raise ConflictError("The end must be after the start.", code="PROMO_WINDOW_INVALID")
        await self.audit.record(
            "promo.updated",
            entity_type="promo_code",
            entity_id=promo.id,
            actor=actor,
            before=before,
            after={"is_active": promo.is_active, "max_uses": promo.max_uses},
        )
        await self.session.commit()
        return promo

    async def delete(self, promo_id: uuid.UUID, *, actor: User) -> None:
        promo = await self.promos.get(promo_id)
        if promo is None:
            raise NotFoundError("Promo code not found.", code="PROMO_NOT_FOUND")
        if promo.used_count:
            raise ConflictError(
                "This code has been used. Switch it off instead of deleting it.",
                code="PROMO_IN_USE",
            )
        await self.audit.record(
            "promo.deleted",
            entity_type="promo_code",
            entity_id=promo.id,
            actor=actor,
            before={"code": promo.code},
        )
        await self.promos.delete(promo)
        await self.session.commit()
