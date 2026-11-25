"""Public archive, for the homepage."""

from __future__ import annotations

from fastapi import APIRouter

from app.dependencies import ArchiveServiceDep
from app.schemas.archive import ArchivePublic

router = APIRouter(tags=["archive"])


@router.get(
    "/archive", response_model=list[ArchivePublic], summary="Archive photos shown on the homepage"
)
async def home_archive(service: ArchiveServiceDep) -> list[ArchivePublic]:
    return [ArchivePublic.model_validate(i) for i in await service.for_home()]
