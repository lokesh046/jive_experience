"""Public artists, for the homepage."""

from __future__ import annotations

from fastapi import APIRouter

from app.dependencies import ArtistServiceDep
from app.schemas.artist import ArtistPublic

router = APIRouter(tags=["artists"])


@router.get("/artists", response_model=list[ArtistPublic], summary="Artists shown on the homepage")
async def home_artists(service: ArtistServiceDep) -> list[ArtistPublic]:
    return [ArtistPublic.model_validate(a) for a in await service.for_home()]
