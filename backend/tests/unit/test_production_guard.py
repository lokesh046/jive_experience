"""The server must refuse to start in production with unsafe settings."""

from __future__ import annotations

import pytest

from app.core.config import DEFAULT_SECRET_KEY, Environment, Settings, assert_production_ready


def production(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "environment": Environment.PRODUCTION,
        "debug": False,
        "secret_key": "s" * 64,
        "cors_origins": ["https://jive.example.com"],
        "trusted_hosts": ["jive.example.com"],
        "log_json": True,
        "google_client_id": "prod-client-id.apps.googleusercontent.com",
        "google_client_secret": "prod-client-secret",
        "google_redirect_uri": "https://jive.example.com/auth/google/callback",
    }
    return Settings(**(base | overrides))  # type: ignore[arg-type]


def test_a_correctly_configured_production_server_starts() -> None:
    assert_production_ready(production())


def test_development_settings_are_never_blocked() -> None:
    assert_production_ready(Settings(environment=Environment.LOCAL))


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"secret_key": DEFAULT_SECRET_KEY}, "development default"),
        ({"secret_key": "too-short"}, "at least 32 characters"),
        ({"debug": True}, "DEBUG"),
        ({"cors_origins": ["*"]}, "CORS_ORIGINS"),
        ({"trusted_hosts": ["*"]}, "TRUSTED_HOSTS"),
        ({"google_client_id": None}, "Google OAuth"),
        ({"google_redirect_uri": "http://jive.example.com/cb"}, "https"),
        ({"log_json": False}, "LOG_JSON"),
    ],
)
def test_unsafe_production_settings_are_refused(
    overrides: dict[str, object], expected: str
) -> None:
    with pytest.raises(RuntimeError, match=expected):
        assert_production_ready(production(**overrides))


def test_every_problem_is_reported_at_once() -> None:
    """One restart should surface every misconfiguration, not the first."""
    with pytest.raises(RuntimeError) as excinfo:
        assert_production_ready(
            production(secret_key=DEFAULT_SECRET_KEY, debug=True, cors_origins=["*"])
        )

    message = str(excinfo.value)
    assert "SECRET_KEY" in message
    assert "DEBUG" in message
    assert "CORS_ORIGINS" in message
