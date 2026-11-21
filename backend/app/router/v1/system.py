"""System endpoints: liveness, readiness and build metadata."""

from __future__ import annotations

from fastapi import APIRouter, Response, status

from app import __version__
from app.core.redis import redis_healthy
from app.db.session import database_healthy
from app.dependencies import AppSettings
from app.models.base import utc_now
from app.schemas.system import (
    DependencyStatus,
    HealthResponse,
    ReadinessResponse,
    ServiceInfo,
)

router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthResponse, summary="Liveness probe")
async def health() -> HealthResponse:
    """Process is up. Deliberately checks nothing else, so a database blip
    never causes the orchestrator to kill a healthy container."""
    return HealthResponse(status="ok", version=__version__)


@router.get("/health/ready", response_model=ReadinessResponse, summary="Readiness probe")
async def readiness(response: Response) -> ReadinessResponse:
    """Dependencies are reachable. The reverse proxy uses this to decide
    whether to route traffic to this instance."""
    db_ok = await database_healthy()
    redis_ok = await redis_healthy()
    ready = db_ok and redis_ok
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(
        status="ready" if ready else "degraded",
        checked_at=utc_now().isoformat(),
        dependencies=DependencyStatus(database=db_ok, redis=redis_ok),
    )


@router.get("/info", response_model=ServiceInfo, summary="Service metadata")
async def service_info(settings: AppSettings) -> ServiceInfo:
    return ServiceInfo(
        name=settings.app_name,
        version=__version__,
        environment=settings.environment.value,
        api_version="v1",
        default_timezone=settings.default_timezone,
        currency=settings.default_currency,
    )
