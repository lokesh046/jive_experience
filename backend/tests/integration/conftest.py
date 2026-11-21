"""Fixtures for tests that need a live PostgreSQL."""

from __future__ import annotations

import os
import secrets
import uuid
from collections.abc import AsyncIterator, Iterator

import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, create_async_engine

from app.core.config import Environment, Settings
from app.core.database_url import normalize_database_url
from app.core.redis import create_redis
from app.db.session import create_engine
from app.dependencies import get_db, set_google_client
from app.main import create_app
from app.models.user import User, UserRole, UserStatus
from tests.integration.google_stub import StubGoogleClient


def integration_database_url() -> str:
    """The database the integration suite may write to and drop tables in.

    Named without a `test_` prefix so pytest does not collect it as a test.

    Named without a `test_` prefix so pytest does not collect it as a test.

    Deliberately **not** `DATABASE_URL`. Once a managed database is configured
    in `.env`, reading that variable here would point the suite — including the
    migration test, which runs `downgrade base` — at the real database. Tests
    get their own local database, or an explicit `TEST_DATABASE_URL`.
    """
    explicit = os.environ.get("TEST_DATABASE_URL")
    if explicit:
        return normalize_database_url(explicit)

    user = os.environ.get("TEST_POSTGRES_USER", "jive")
    password = os.environ.get("TEST_POSTGRES_PASSWORD", "jive")
    host = os.environ.get("TEST_POSTGRES_HOST", "localhost")
    port = os.environ.get("TEST_POSTGRES_PORT", "5432")
    name = os.environ.get("TEST_POSTGRES_DB", "jive_events")
    return f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{name}"


@pytest.fixture
async def db_connection() -> AsyncIterator[AsyncConnection]:
    """A connection whose work is rolled back after the test."""
    engine = create_async_engine(integration_database_url())
    try:
        conn = await engine.connect()
    except Exception as exc:
        await engine.dispose()
        pytest.skip(f"PostgreSQL unavailable: {exc}")

    transaction = await conn.begin()
    try:
        await conn.execute(sa.text("SELECT 1"))
        yield conn
    finally:
        await transaction.rollback()
        await conn.close()
        await engine.dispose()


@pytest.fixture
async def db_session(db_connection: AsyncConnection) -> AsyncIterator[AsyncSession]:
    """An ORM session whose commits are undone when the test ends.

    `join_transaction_mode="create_savepoint"` makes `session.commit()` release
    a savepoint instead of committing for real, so service code can commit
    normally and the outer transaction still rolls the test's data away.
    """
    async with AsyncSession(
        bind=db_connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    ) as session:
        yield session


VALID_CODE = "google-auth-code-valid"


def unique_email(prefix: str = "user") -> str:
    """A fresh address per call.

    Integration tests must not assume an empty database — the development
    database holds whatever the last manual run left behind, and a fixed
    address makes a test fail for a reason that has nothing to do with the
    behaviour under test.
    """
    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"


def unique_phone() -> str:
    """A fresh E.164 Indian mobile number per call."""
    return f"+919{secrets.randbelow(10**9):09d}"


@pytest.fixture
def auth_settings() -> Settings:
    return Settings(
        environment=Environment.TEST,
        secret_key="t" * 64,
        log_json=False,
        log_level="WARNING",
        rate_limit_enabled=False,
        allowed_phone_country_codes=["+91"],
        google_client_id="test-client-id.apps.googleusercontent.com",
        google_client_secret="test-client-secret",
        google_redirect_uri="http://localhost:3000/auth/google/callback",
        database_url=integration_database_url(),
    )


@pytest.fixture
def customer_phone() -> str:
    return unique_phone()


@pytest.fixture
def customer_email() -> str:
    return unique_email("customer")


@pytest.fixture
def google(customer_email: str) -> Iterator[StubGoogleClient]:
    stub = StubGoogleClient()
    stub.register(
        VALID_CODE,
        subject=f"google-sub-{uuid.uuid4().hex[:12]}",
        email=customer_email,
        full_name="Asha Rao",
        picture="https://example.com/a.png",
    )
    set_google_client(stub)  # type: ignore[arg-type]
    yield stub
    set_google_client(None)


@pytest.fixture
async def api(
    auth_settings: Settings,
    google: StubGoogleClient,
    db_session: AsyncSession,
) -> AsyncIterator[AsyncClient]:
    """App wired to the rolled-back test session, so nothing persists."""
    create_engine(auth_settings)
    create_redis(auth_settings)
    app: FastAPI = create_app(auth_settings)

    async def _session_override() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db] = _session_override

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def seed_admin(session: AsyncSession, email: str | None = None) -> User:
    """Pre-provision an administrator, the way the CLI or dashboard does.

    No `google_sub`: the row exists first, and the Google identity is linked
    the first time that person signs in. That is exactly the production
    permission model, so tests exercise it rather than a shortcut.
    """
    admin = User(
        role=UserRole.ADMIN,
        status=UserStatus.ACTIVE,
        email=email or unique_email("admin"),
        full_name="Ops Admin",
    )
    session.add(admin)
    await session.flush()
    return admin


async def seed_staff(session: AsyncSession, email: str | None = None) -> User:
    staff = User(
        role=UserRole.EVENT_STAFF,
        status=UserStatus.ACTIVE,
        email=email or unique_email("staff"),
        full_name="Gate Staff",
    )
    session.add(staff)
    await session.flush()
    return staff


async def sign_in_with_google(api: AsyncClient, code: str = VALID_CODE) -> dict:
    """Run the full OAuth flow: authorize, then callback with that state."""
    started = await api.get("/api/v1/auth/google/authorize")
    assert started.status_code == 200, started.text
    state = started.json()["state"]
    response = await api.post("/api/v1/auth/google/callback", json={"code": code, "state": state})
    return {"response": response, "state": state}


async def sign_in_as(api: AsyncClient, google: StubGoogleClient, user: User) -> str:
    """Sign a pre-provisioned account in and return its access token.

    The production path for staff and administrators: the row already carries
    the role, and the verified Google email links the identity to it.
    """
    code = f"google-code-{uuid.uuid4().hex[:10]}"
    google.register(code, subject=f"google-sub-{uuid.uuid4().hex[:12]}", email=user.email)
    result = await sign_in_with_google(api, code)
    assert result["response"].status_code == 200, result["response"].text
    return str(result["response"].json()["access_token"])


async def customer_session(api: AsyncClient, google: StubGoogleClient) -> dict[str, str]:
    """Sign the fixture customer in and return both tokens.

    A fresh authorization code each time, cloned from the fixture identity:
    Google issues single-use codes and the stub enforces that, so re-using one
    would fail exactly as it would in production.
    """
    code = f"google-code-{uuid.uuid4().hex[:10]}"
    google.identities[code] = google.identities[VALID_CODE]
    result = await sign_in_with_google(api, code)
    body = result["response"].json()
    assert "access_token" in body, body
    return {"access": body["access_token"], "refresh": body["refresh_token"]}
