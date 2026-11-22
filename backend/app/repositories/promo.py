from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any, cast

from sqlalchemy import CursorResult, func, select, update

from app.core.pagination import PageParams
from app.models.commerce import Booking, BookingStatus
from app.models.promo import PromoCode
from app.repositories.base import BaseRepository


class PromoRepository(BaseRepository[PromoCode]):
    model = PromoCode

    async def by_code(self, code: str) -> PromoCode | None:
        return await self.find_one(PromoCode.code == code)

    async def page(self, params: PageParams) -> tuple[Sequence[PromoCode], int]:
        return await self.paginate(params, order_by=[PromoCode.created_at.desc()])

    async def take_use(self, promo_id: uuid.UUID) -> bool:
        """Count one use if any are left: the whole "first 100 buyers" guarantee."""
        statement = (
            update(PromoCode)
            .where(
                PromoCode.id == promo_id,
                (PromoCode.max_uses.is_(None)) | (PromoCode.used_count < PromoCode.max_uses),
            )
            .values(used_count=PromoCode.used_count + 1)
        )
        result = cast("CursorResult[Any]", await self.session.execute(statement))
        return (result.rowcount or 0) == 1

    async def give_back_use(self, promo_id: uuid.UUID) -> None:
        statement = (
            update(PromoCode)
            .where(PromoCode.id == promo_id, PromoCode.used_count > 0)
            .values(used_count=PromoCode.used_count - 1)
        )
        await self.session.execute(statement)

    async def uses_by_customer(self, promo_id: uuid.UUID, user_id: uuid.UUID) -> int:
        """Bookings this customer made with the code that did not simply lapse."""
        statement = select(func.count()).where(
            Booking.promo_code_id == promo_id,
            Booking.user_id == user_id,
            Booking.status != BookingStatus.EXPIRED,
        )
        return int((await self.session.execute(statement)).scalar_one())
