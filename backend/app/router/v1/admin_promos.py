"""Administrator promo codes."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from app.dependencies import Pagination, PromoServiceDep, RequireAdmin
from app.schemas.promo import PromoCreate, PromoOut, PromoPage, PromoUpdate

router = APIRouter(tags=["admin: promo codes"])


@router.get("/promos", response_model=PromoPage, summary="Promo codes, newest first")
async def list_promos(
    actor: RequireAdmin, service: PromoServiceDep, pagination: Pagination
) -> PromoPage:
    rows, total = await service.list_codes(pagination)
    return PromoPage(
        items=[PromoOut.model_validate(r) for r in rows],
        total=total,
        page=pagination.page,
        size=pagination.size,
    )


@router.post(
    "/promos", response_model=PromoOut, status_code=status.HTTP_201_CREATED, summary="Create a code"
)
async def create_promo(
    payload: PromoCreate, actor: RequireAdmin, service: PromoServiceDep
) -> PromoOut:
    """The discount, scope and code cannot be edited afterwards: make a new code instead."""
    return PromoOut.model_validate(await service.create(payload, actor=actor))


@router.patch(
    "/promos/{promo_id}",
    response_model=PromoOut,
    summary="Switch a code on or off, or change its limits",
)
async def update_promo(
    promo_id: uuid.UUID, payload: PromoUpdate, actor: RequireAdmin, service: PromoServiceDep
) -> PromoOut:
    return PromoOut.model_validate(await service.update(promo_id, payload, actor=actor))


@router.delete(
    "/promos/{promo_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a code that has never been used",
)
async def delete_promo(promo_id: uuid.UUID, actor: RequireAdmin, service: PromoServiceDep) -> None:
    await service.delete(promo_id, actor=actor)
