"""Administrator artists: the people shown on the homepage."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from app.dependencies import ArtistServiceDep, RequireAdmin
from app.schemas.artist import ArtistIn, ArtistOrder, ArtistOut, ArtistUpdate

router = APIRouter(tags=["admin: artists"])


@router.get("/artists", response_model=list[ArtistOut], summary="All artists, in display order")
async def list_artists(actor: RequireAdmin, service: ArtistServiceDep) -> list[ArtistOut]:
    return [ArtistOut.model_validate(a) for a in await service.list_all()]


@router.post(
    "/artists",
    response_model=ArtistOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add an artist",
)
async def create_artist(
    payload: ArtistIn, actor: RequireAdmin, service: ArtistServiceDep
) -> ArtistOut:
    return ArtistOut.model_validate(await service.create(payload, actor=actor))


@router.put("/artists/order", response_model=list[ArtistOut], summary="Set the display order")
async def reorder_artists(
    payload: ArtistOrder, actor: RequireAdmin, service: ArtistServiceDep
) -> list[ArtistOut]:
    return [ArtistOut.model_validate(a) for a in await service.reorder(payload, actor=actor)]


@router.patch("/artists/{artist_id}", response_model=ArtistOut, summary="Edit an artist")
async def update_artist(
    artist_id: uuid.UUID, payload: ArtistUpdate, actor: RequireAdmin, service: ArtistServiceDep
) -> ArtistOut:
    return ArtistOut.model_validate(await service.update(artist_id, payload, actor=actor))


@router.delete(
    "/artists/{artist_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Remove an artist"
)
async def delete_artist(
    artist_id: uuid.UUID, actor: RequireAdmin, service: ArtistServiceDep
) -> None:
    await service.delete(artist_id, actor=actor)
