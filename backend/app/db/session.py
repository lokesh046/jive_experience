"""Async engine and session management.

Transaction policy
------------------
`get_db` hands out a session but never commits on your behalf. Service code
owns its transaction boundary explicitly:

    async with session.begin():        # or: ... ; await session.commit()
        ...

This matters for inventory and payments, where the exact span of a transaction
(and the rows locked inside it) is part of the correctness argument rather than
an implementation detail.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings

logger = structlog.get_logger(__name__)

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def create_engine(settings: Settings) -> AsyncEngine:
    """Create the process-wide async engine and session factory."""
    global _engine, _sessionmaker

    # Behind a transaction pooler the provider already multiplexes
    # connections, so a large local pool only consumes the provider's
    # connection allowance. pool_pre_ping matters more there than anywhere:
    # a serverless database suspends when idle and drops its connections.
    pool_size = 5 if settings.uses_transaction_pooler else settings.db_pool_size
    max_overflow = 5 if settings.uses_transaction_pooler else settings.db_max_overflow

    _engine = create_async_engine(
        settings.sqlalchemy_dsn,
        echo=settings.db_echo,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_timeout=settings.db_pool_timeout,
        pool_recycle=settings.db_pool_recycle,
        pool_pre_ping=True,
        connect_args=settings.database_connect_args,
    )
    _sessionmaker = async_sessionmaker(
        bind=_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    if _sessionmaker is None:  # pragma: no cover - programming error
        raise RuntimeError("Sessionmaker not initialised; call create_engine() first.")
    return _sessionmaker


async def dispose_engine() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _sessionmaker = None


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a request-scoped session."""
    async with get_sessionmaker()() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def database_healthy() -> bool:
    try:
        async with get_sessionmaker()() as session:
            await session.execute(text("SELECT 1"))
        return True
    except Exception as exc:
        logger.warning("database_health_check_failed", error=str(exc))
        return False
