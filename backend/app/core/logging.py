"""Structured logging setup.

Development renders human-readable lines; every other environment emits JSON so
the VPS log shipper can parse it. A per-request correlation id is bound via
contextvars by `RequestContextMiddleware` and therefore appears on every log
record emitted while handling that request.
"""

from __future__ import annotations

import logging
import sys

import structlog
from structlog.types import Processor

from app.core.config import Settings


def configure_logging(settings: Settings) -> None:
    """Configure stdlib logging and structlog as a single pipeline."""
    level = logging.getLevelNamesMapping()[settings.log_level]

    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    renderer: Processor = (
        structlog.processors.JSONRenderer()
        if settings.log_json
        else structlog.dev.ConsoleRenderer(colors=True)
    )

    # structlog hands the event dict to stdlib logging and the handler below
    # renders it exactly once. Ending this chain with a renderer instead would
    # render the line twice — once here and again in the handler.
    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Route stdlib loggers (uvicorn, sqlalchemy, alembic) through structlog.
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared_processors,
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.processors.format_exc_info,
                renderer,
            ],
        )
    )

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)

    for noisy in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(noisy).handlers = []
        logging.getLogger(noisy).propagate = True

    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(
        logging.INFO if settings.db_echo else logging.WARNING
    )
