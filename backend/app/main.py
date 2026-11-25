"""Application entry point.

A factory (`create_app`) is used rather than a module-level app so tests can
build an isolated instance with overridden settings.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app import __version__
from app.core.config import Environment, Settings, assert_production_ready, get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware, SecurityHeadersMiddleware
from app.core.redis import close_redis, create_redis, get_redis
from app.db.session import create_engine, dispose_engine, get_sessionmaker
from app.router.v1 import system
from app.router.v1.router import api_router
from app.services.health import HealthService

logger = structlog.get_logger(__name__)

DESCRIPTION = """
REST API for the JIVE event management, entertainment and ticketing platform.

The same versioned surface serves the public website, the customer booking
flow, the admin dashboard, the event-staff scanner and future mobile clients.

### Trying these endpoints

Most require a bearer token. Two ways to get one:

1. **From the shell** — fastest while there is no frontend:
   `python -m app.cli dev-token --email you@gmail.com`
2. **The real flow** — `GET /auth/google/authorize`, open the returned URL,
   sign in, then post the `code` and `state` from the redirect URL back to
   `POST /auth/google/callback`.

Then press **Authorize** above and paste the access token.

Access tokens last 15 minutes; use `POST /auth/refresh` with the refresh token
rather than signing in again.
"""

TAGS_METADATA = [
    {"name": "auth", "description": "Google sign-in, session refresh and logout."},
    {"name": "users", "description": "Profiles, and granting staff access."},
    {"name": "events", "description": "Public catalogue. No authentication."},
    {"name": "bookings", "description": "Customer booking, checkout and cancellation."},
    {"name": "tickets", "description": "A customer's QR tickets."},
    {
        "name": "payments",
        "description": "Gateway webhook. Authenticated by signature, not a token.",
    },
    {"name": "scanner", "description": "Event-staff gate scanner. Assignment enforced."},
    {"name": "admin: catalogue", "description": "Venues, events and ticket categories."},
    {"name": "admin: commerce", "description": "Bookings, refunds and staff assignment."},
    {"name": "system", "description": "Health probes and build metadata."},
]


async def _watch_worker(interval: float) -> None:
    """Every minute, look at the worker's heartbeat and the queue, and alert on a change.

    Runs in the API because the worker cannot report its own death. One alert per outage is
    guaranteed by the alert's own key, so several API processes watching is harmless; the lock
    only saves them repeating the work.
    """
    sessionmaker = get_sessionmaker()
    while True:
        try:
            if await get_redis().set("health:monitor", "1", ex=max(10, int(interval) - 5), nx=True):
                async with sessionmaker() as session:
                    await HealthService(session).check_and_alert(datetime.now(UTC))
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("health_check_failed")
        await asyncio.sleep(interval)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Open the database and Redis connections; close them on shutdown."""
    settings: Settings = app.state.settings
    create_engine(settings)
    create_redis(settings)
    logger.info(
        "application_started",
        environment=settings.environment.value,
        version=__version__,
    )
    watcher: asyncio.Task[None] | None = None
    if settings.environment is not Environment.TEST and settings.health_check_interval_seconds > 0:
        watcher = asyncio.create_task(_watch_worker(settings.health_check_interval_seconds))
    try:
        yield
    finally:
        if watcher is not None:
            watcher.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await watcher
        await close_redis()
        await dispose_engine()
        logger.info("application_stopped")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings)
    assert_production_ready(settings)

    app = FastAPI(
        title=settings.app_name,
        description=DESCRIPTION,
        version=__version__,
        openapi_tags=TAGS_METADATA,
        lifespan=lifespan,
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None if settings.is_production else "/redoc",
        openapi_url=None if settings.is_production else "/openapi.json",
        swagger_ui_parameters={
            # Keeps the pasted token across page reloads, so exercising the
            # whole surface does not mean re-authorising after every refresh.
            "persistAuthorization": True,
            "displayRequestDuration": True,
            "filter": True,
            "tryItOutEnabled": True,
        },
    )

    # Set before anything can read it: the lifespan and every dependency
    # resolve settings from here, so an app built by the test factory never
    # falls back to the process environment.
    app.state.settings = settings

    # Middleware runs bottom-up: security headers wrap the response last,
    # request context wraps everything so the correlation id covers CORS
    # rejections too.
    app.add_middleware(SecurityHeadersMiddleware, settings=settings)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID", "Idempotency-Key"],
        expose_headers=["X-Request-ID", "X-RateLimit-Remaining"],
        max_age=600,
    )
    if settings.trusted_hosts != ["*"]:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts)
    app.add_middleware(RequestContextMiddleware)

    register_exception_handlers(app, settings)

    app.include_router(api_router, prefix=settings.api_v1_prefix)
    # Unversioned probes for the orchestrator and reverse proxy.
    app.include_router(system.router, include_in_schema=False)

    return app


app = create_app()
