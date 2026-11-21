"""Migrations must apply to an empty database and fully reverse.

These tests run `downgrade base`, which drops every table. They therefore run
against a **throwaway database of their own**, created on demand — running the
test suite must never destroy the developer's local data.

Requires PostgreSQL (`make db`). Skipped automatically when unreachable.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import AsyncIterator

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from tests.integration.conftest import integration_database_url

pytestmark = pytest.mark.integration

MIGRATION_DB = "jive_events_migration_test"
EXPECTED_TABLES = {"users", "refresh_tokens", "audit_logs", "alembic_version"}


def _dsn_for(database: str) -> str:
    """Point at `database` on the *test* server, never at `DATABASE_URL`."""
    base = integration_database_url().rsplit("/", 1)[0]
    return f"{base}/{database}"


def _alembic(dsn: str, *args: str) -> subprocess.CompletedProcess[str]:
    """Run alembic against an explicit database.

    Invoked through this interpreter: the venv's bin directory is not
    necessarily on PATH when pytest runs as `.venv/bin/python -m pytest`.
    `DATABASE_URL` overrides the discrete POSTGRES_* settings.
    """
    import os

    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "DATABASE_URL": dsn},
    )


@pytest.fixture
async def migration_dsn() -> AsyncIterator[str]:
    """A dedicated, empty database for the duration of the test."""
    admin_engine = create_async_engine(_dsn_for("postgres"), isolation_level="AUTOCOMMIT")
    try:
        async with admin_engine.connect() as conn:
            await conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{MIGRATION_DB}" WITH (FORCE)'))
            await conn.execute(sa.text(f'CREATE DATABASE "{MIGRATION_DB}"'))
    except Exception as exc:
        pytest.skip(f"PostgreSQL unavailable: {exc}")
    finally:
        await admin_engine.dispose()

    yield _dsn_for(MIGRATION_DB)

    cleanup_engine = create_async_engine(_dsn_for("postgres"), isolation_level="AUTOCOMMIT")
    async with cleanup_engine.connect() as conn:
        await conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{MIGRATION_DB}" WITH (FORCE)'))
    await cleanup_engine.dispose()


async def test_upgrade_creates_every_table(migration_dsn: str) -> None:
    result = _alembic(migration_dsn, "upgrade", "head")
    assert result.returncode == 0, result.stderr

    engine = create_async_engine(migration_dsn)
    async with engine.connect() as conn:
        names = await conn.run_sync(lambda c: set(sa.inspect(c).get_table_names()))
    await engine.dispose()

    assert names >= EXPECTED_TABLES


async def test_schema_matches_models_with_no_pending_changes(migration_dsn: str) -> None:
    """Autogenerate against an up-to-date database must find nothing.

    Catches the common failure where a model is edited but the migration is
    forgotten. Note it does **not** catch CHECK constraint drift — Alembic
    cannot see those — which is what `test_user_constraints.py` is for.
    """
    assert _alembic(migration_dsn, "upgrade", "head").returncode == 0

    result = _alembic(migration_dsn, "check")
    assert result.returncode == 0, (
        f"Models and migrations have drifted apart:\n{result.stdout}\n{result.stderr}"
    )


async def test_every_migration_reverses_cleanly(migration_dsn: str) -> None:
    """`downgrade` then `upgrade` is the path a failed production deploy takes.

    A migration that cannot be reversed — a leftover enum type, a dropped
    constraint that is never recreated — turns a bad deploy into an outage.
    """
    assert _alembic(migration_dsn, "upgrade", "head").returncode == 0

    down = _alembic(migration_dsn, "downgrade", "base")
    assert down.returncode == 0, down.stderr

    engine = create_async_engine(migration_dsn)
    async with engine.connect() as conn:
        remaining = await conn.run_sync(lambda c: set(sa.inspect(c).get_table_names()))
    await engine.dispose()
    assert remaining <= {"alembic_version"}, f"downgrade left tables behind: {remaining}"

    up_again = _alembic(migration_dsn, "upgrade", "head")
    assert up_again.returncode == 0, (
        f"re-upgrade after downgrade failed — usually a PostgreSQL ENUM type "
        f"that downgrade did not drop:\n{up_again.stderr}"
    )
