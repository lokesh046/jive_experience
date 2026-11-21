"""Database URL normalisation, using the URL shapes providers actually emit."""

from __future__ import annotations

import pytest

from app.core.database_url import (
    asyncpg_connect_args,
    is_transaction_pooler,
    normalize_database_url,
    requires_ssl,
)

NEON_POOLED = (
    "postgresql://neondb_owner:npg_secret@"
    "ep-cool-name-a1b2c3d4-pooler.ap-southeast-1.aws.neon.tech/neondb"
    "?sslmode=require&channel_binding=require"
)
NEON_DIRECT = (
    "postgresql://neondb_owner:npg_secret@"
    "ep-cool-name-a1b2c3d4.ap-southeast-1.aws.neon.tech/neondb?sslmode=require"
)
LOCAL = "postgresql+asyncpg://jive:jive@localhost:5432/jive_events"


# -------------------------------------------------------------- normalisation ---


def test_neon_url_becomes_an_asyncpg_dsn() -> None:
    dsn = normalize_database_url(NEON_POOLED)
    assert dsn.startswith("postgresql+asyncpg://")


@pytest.mark.parametrize("param", ["sslmode", "channel_binding"])
def test_libpq_only_parameters_are_removed(param: str) -> None:
    """asyncpg raises TypeError on these, so they must not reach it."""
    assert param not in normalize_database_url(NEON_POOLED)


def test_postgres_scheme_is_also_handled() -> None:
    dsn = normalize_database_url("postgres://u:p@host/db?sslmode=require")
    assert dsn == "postgresql+asyncpg://u:p@host/db"


def test_credentials_host_and_database_survive() -> None:
    dsn = normalize_database_url(NEON_POOLED)
    assert "neondb_owner:npg_secret@" in dsn
    assert "ep-cool-name-a1b2c3d4-pooler.ap-southeast-1.aws.neon.tech" in dsn
    assert dsn.endswith("/neondb")


def test_an_already_async_dsn_is_left_alone() -> None:
    assert normalize_database_url(LOCAL) == LOCAL


def test_normalisation_is_idempotent() -> None:
    once = normalize_database_url(NEON_POOLED)
    assert normalize_database_url(once) == once


def test_surrounding_whitespace_is_tolerated() -> None:
    """Pasting from a console usually brings a trailing newline."""
    assert normalize_database_url(f"  {NEON_DIRECT}\n").startswith("postgresql+asyncpg://")


# ----------------------------------------------------------------------- ssl ---


@pytest.mark.parametrize("mode", ["require", "verify-full", "verify-ca", "prefer"])
def test_ssl_modes_are_detected(mode: str) -> None:
    assert requires_ssl(f"postgresql://u:p@host/db?sslmode={mode}")


def test_disabled_ssl_is_detected() -> None:
    assert not requires_ssl("postgresql://u:p@host/db?sslmode=disable")


def test_local_url_without_sslmode_does_not_request_ssl() -> None:
    assert not requires_ssl(LOCAL)


# -------------------------------------------------------------------- pooler ---


def test_neon_pooled_endpoint_is_detected() -> None:
    assert is_transaction_pooler(NEON_POOLED)


def test_neon_direct_endpoint_is_not_a_pooler() -> None:
    assert not is_transaction_pooler(NEON_DIRECT)


def test_local_database_is_not_a_pooler() -> None:
    assert not is_transaction_pooler(LOCAL)


# ------------------------------------------------------------- connect args ---


def test_pooled_connection_disables_prepared_statements() -> None:
    """Transaction pooling and server-side prepared statements are
    incompatible; leaving the cache on fails only after a reconnect."""
    args = asyncpg_connect_args(NEON_POOLED, application_name="JIVE")
    assert args["statement_cache_size"] == 0
    assert args["prepared_statement_cache_size"] == 0
    assert args["ssl"] == "require"


def test_direct_connection_keeps_the_statement_cache() -> None:
    args = asyncpg_connect_args(NEON_DIRECT, application_name="JIVE")
    assert "statement_cache_size" not in args
    assert args["ssl"] == "require"


def test_local_connection_asks_for_neither() -> None:
    args = asyncpg_connect_args(LOCAL, application_name="JIVE")
    assert "ssl" not in args
    assert "statement_cache_size" not in args


def test_application_name_is_always_set() -> None:
    """Named connections are what make `pg_stat_activity` readable during an
    incident."""
    args = asyncpg_connect_args(LOCAL, application_name="JIVE Events API")
    assert args["server_settings"]["application_name"] == "JIVE Events API"
