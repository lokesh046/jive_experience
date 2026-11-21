"""Configuration behaviour that other code depends on."""

from __future__ import annotations

import pytest

from app.core.config import Environment, Settings


def test_dsn_is_built_from_discrete_fields() -> None:
    settings = Settings(
        postgres_user="u",
        postgres_password="p",
        postgres_host="db",
        postgres_port=5433,
        postgres_db="events",
    )
    assert settings.sqlalchemy_dsn == "postgresql+asyncpg://u:p@db:5433/events"


def test_explicit_database_url_wins() -> None:
    settings = Settings(
        database_url="postgresql+asyncpg://x:y@other:5432/z", postgres_host="ignored"
    )
    assert settings.sqlalchemy_dsn.endswith("@other:5432/z")


def test_async_driver_is_always_used() -> None:
    assert Settings().sqlalchemy_dsn.startswith("postgresql+asyncpg://")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("http://a.com,http://b.com", ["http://a.com", "http://b.com"]),
        ("http://a.com , http://b.com ", ["http://a.com", "http://b.com"]),
        ('["http://a.com"]', ["http://a.com"]),
    ],
)
def test_cors_origins_accept_csv_or_json(raw: str, expected: list[str]) -> None:
    assert Settings(cors_origins=raw).cors_origins == expected


def test_password_is_not_exposed_by_repr() -> None:
    settings = Settings(postgres_password="super-secret", secret_key="also-secret")
    rendered = repr(settings)
    assert "super-secret" not in rendered
    assert "also-secret" not in rendered


def test_is_production_flag() -> None:
    assert Settings(environment=Environment.PRODUCTION).is_production
    assert not Settings(environment=Environment.LOCAL).is_production


def test_access_token_ttl_is_bounded() -> None:
    """Short-lived access tokens are a security requirement, not a preference."""
    with pytest.raises(ValueError):
        Settings(access_token_ttl_seconds=86_400)
