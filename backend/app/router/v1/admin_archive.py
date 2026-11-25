"""Administrator archive: the photos of past nights shown on the homepage."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from app.dependencies import ArchiveServiceDep, RequireAdmin
from app.schemas.archive import ArchiveIn, ArchiveOrder, ArchiveOut, ArchiveUpdate

router = APIRouter(tags=["admin: archive"])


@router.get("/archive", response_model=list[ArchiveOut], summary="All archive photos, in order")
async def list_archive(actor: RequireAdmin, service: ArchiveServiceDep) -> list[ArchiveOut]:
    return [ArchiveOut.model_validate(i) for i in await service.list_all()]


@router.post(
    "/archive",
    response_model=ArchiveOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add an archive photo",
)
async def create_archive_item(
    payload: ArchiveIn, actor: RequireAdmin, service: ArchiveServiceDep
) -> ArchiveOut:
    return ArchiveOut.model_validate(await service.create(payload, actor=actor))


@router.put("/archive/order", response_model=list[ArchiveOut], summary="Set the display order")
async def reorder_archive(
    payload: ArchiveOrder, actor: RequireAdmin, service: ArchiveServiceDep
) -> list[ArchiveOut]:
    return [ArchiveOut.model_validate(i) for i in await service.reorder(payload, actor=actor)]


@router.patch("/archive/{item_id}", response_model=ArchiveOut, summary="Edit an archive photo")
async def update_archive_item(
    item_id: uuid.UUID, payload: ArchiveUpdate, actor: RequireAdmin, service: ArchiveServiceDep
) -> ArchiveOut:
    return ArchiveOut.model_validate(await service.update(item_id, payload, actor=actor))


@router.delete(
    "/archive/{item_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Remove an archive photo"
)
async def delete_archive_item(
    item_id: uuid.UUID, actor: RequireAdmin, service: ArchiveServiceDep
) -> None:
    await service.delete(item_id, actor=actor)
