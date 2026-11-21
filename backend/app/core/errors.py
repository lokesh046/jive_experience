"""Centralised error model and exception handlers.

Every error leaving the API uses one envelope so that the web app, the admin
dashboard, the staff scanner and future mobile clients can all handle failures
with a single code path:

    {"error": {"code": "...", "message": "...", "details": {...},
               "request_id": "..."}}

`code` is a stable machine-readable string — clients branch on it, never on the
human-readable `message`.
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import Settings

logger = structlog.get_logger(__name__)


class AppError(Exception):
    """Base class for every expected (handled) application failure."""

    code: str = "INTERNAL_ERROR"
    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    message: str = "An unexpected error occurred."

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        status_code: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.message = message or self.message
        self.code = code or self.code
        self.status_code = status_code or self.status_code
        self.details = details or {}
        super().__init__(self.message)


class AuthenticationError(AppError):
    code = "UNAUTHENTICATED"
    status_code = status.HTTP_401_UNAUTHORIZED
    message = "Authentication is required."


class PermissionDeniedError(AppError):
    code = "PERMISSION_DENIED"
    status_code = status.HTTP_403_FORBIDDEN
    message = "You do not have permission to perform this action."


class NotFoundError(AppError):
    code = "NOT_FOUND"
    status_code = status.HTTP_404_NOT_FOUND
    message = "The requested resource was not found."


class ConflictError(AppError):
    """State conflict — e.g. double check-in, duplicate gateway event."""

    code = "CONFLICT"
    status_code = status.HTTP_409_CONFLICT
    message = "The request conflicts with the current state of the resource."


class BusinessRuleError(AppError):
    """A valid request that the domain rules refuse — e.g. refund past deadline."""

    code = "BUSINESS_RULE_VIOLATION"
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    message = "The request is not allowed by the applicable business rules."


class RateLimitedError(AppError):
    code = "RATE_LIMITED"
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    message = "Too many requests. Please retry later."


class ServiceUnavailableError(AppError):
    """A dependency (database, cache, payment gateway) is unavailable."""

    code = "SERVICE_UNAVAILABLE"
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    message = "A required service is temporarily unavailable."


def _envelope(
    request: Request,
    *,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
            "request_id": getattr(request.state, "request_id", None),
        }
    }


def register_exception_handlers(app: FastAPI, settings: Settings) -> None:
    """Attach the handlers that produce the error envelope."""

    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> JSONResponse:
        log = logger.bind(error_code=exc.code, path=request.url.path)
        if exc.status_code >= 500:
            log.error("app_error", exc_info=exc)
        else:
            log.info("app_error", message=exc.message)
        return JSONResponse(
            status_code=exc.status_code,
            content=_envelope(request, code=exc.code, message=exc.message, details=exc.details),
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content=_envelope(
                request,
                code="VALIDATION_ERROR",
                message="One or more fields failed validation.",
                details={"fields": jsonable_encoder(exc.errors())},
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {
            401: "UNAUTHENTICATED",
            403: "PERMISSION_DENIED",
            404: "NOT_FOUND",
            405: "METHOD_NOT_ALLOWED",
            429: "RATE_LIMITED",
        }.get(exc.status_code, "HTTP_ERROR")
        return JSONResponse(
            status_code=exc.status_code,
            content=_envelope(request, code=code, message=str(exc.detail)),
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        logger.bind(path=request.url.path, method=request.method).exception("unhandled_exception")
        # Internal details are never leaked outside local/test environments.
        message = (
            f"{type(exc).__name__}: {exc}"
            if not settings.is_production
            else "An unexpected error occurred."
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_envelope(request, code="INTERNAL_ERROR", message=message),
        )
