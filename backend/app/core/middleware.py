"""HTTP middleware: request correlation, access logging, security headers."""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from app.core.config import Settings

logger = structlog.get_logger("http")

REQUEST_ID_HEADER = "X-Request-ID"

_Next = Callable[[Request], Awaitable[Response]]


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assign a correlation id, bind it to the log context, time the request."""

    async def dispatch(self, request: Request, call_next: _Next) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex
        request.state.request_id = request_id

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
        )

        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            duration_ms = (time.perf_counter() - started) * 1000
            logger.exception("request_failed", duration_ms=round(duration_ms, 2))
            raise

        duration_ms = (time.perf_counter() - started) * 1000
        response.headers[REQUEST_ID_HEADER] = request_id
        response.headers["Server-Timing"] = f"app;dur={duration_ms:.1f}"

        # Health probes would otherwise dominate the log volume.
        if not request.url.path.startswith("/health"):
            logger.info(
                "request_completed",
                status_code=response.status_code,
                duration_ms=round(duration_ms, 2),
            )
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Baseline response hardening.

    HSTS is only emitted in production, where TLS termination at the reverse
    proxy is guaranteed; sending it from a local HTTP dev server would pin the
    browser to https://localhost.
    """

    def __init__(self, app: ASGIApp, *, settings: Settings) -> None:
        super().__init__(app)
        self._settings = settings

    async def dispatch(self, request: Request, call_next: _Next) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Permissions-Policy", "geolocation=(), microphone=(), camera=(self)"
        )
        if self._settings.is_production:
            response.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains",
            )
        return response
