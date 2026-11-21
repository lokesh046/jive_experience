"""Shared test fixtures.

Unit tests run without PostgreSQL or Redis: `create_engine` and `create_redis`
build lazy clients that do not connect until a query is issued, so the app can
be constructed and exercised offline. Tests that genuinely need a database are
marked `integration`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.config import Environment, Settings
from app.core.redis import create_redis
from app.db.session import create_engine
from app.main import create_app


@pytest.fixture(autouse=True, scope="session")
def _isolate_settings_from_dotenv() -> Iterator[None]:
    """Stop tests reading the developer's `.env`.

    Once a real `DATABASE_URL` or set of Google credentials is configured
    locally, a test that builds `Settings()` would silently inherit them —
    asserting against whatever happens to be in the developer's file, and in
    the worst case pointing the suite at the live database. Tests supply every
    value they depend on explicitly.
    """
    original = Settings.model_config.get("env_file")
    Settings.model_config["env_file"] = None
    yield
    Settings.model_config["env_file"] = original


@pytest.fixture(scope="session")
def settings() -> Settings:
    return Settings(
        environment=Environment.TEST,
        debug=True,
        log_json=False,
        log_level="WARNING",
        rate_limit_enabled=False,
        postgres_db="jive_events_test",
    )


@pytest.fixture
def app(settings: Settings) -> Iterator[FastAPI]:
    application = create_app(settings)
    # ASGITransport does not execute the lifespan, so initialise the lazy
    # clients the dependencies expect.
    create_engine(settings)
    create_redis(settings)
    yield application


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
