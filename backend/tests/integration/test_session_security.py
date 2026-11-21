"""What every authenticated request verifies, proved end to end.

The customer path is the one that matters most here: a customer's token is the
only thing standing between a stranger and someone else's bookings and
tickets. These tests run against the real dependency chain, not a mock of it.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.security import create_access_token
from tests.integration.conftest import (
    customer_session,
    seed_admin,
    sign_in_as,
    sign_in_with_google,
    unique_email,
)
from tests.integration.google_stub import StubGoogleClient

pytestmark = pytest.mark.integration


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# Representative customer-side endpoints; each goes through the same
# `get_current_user` dependency.
CUSTOMER_ENDPOINTS = [
    ("GET", "/api/v1/auth/me"),
    ("GET", "/api/v1/users/me"),
    ("GET", "/api/v1/bookings"),
    ("GET", "/api/v1/tickets"),
]


# ------------------------------------------------------- the token itself ---


@pytest.mark.parametrize(("method", "path"), CUSTOMER_ENDPOINTS)
async def test_no_token_is_refused(api: AsyncClient, method: str, path: str) -> None:
    response = await api.request(method, path)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


@pytest.mark.parametrize(("method", "path"), CUSTOMER_ENDPOINTS)
async def test_garbage_token_is_refused(api: AsyncClient, method: str, path: str) -> None:
    response = await api.request(method, path, headers=bearer("not-a-token"))
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "TOKEN_INVALID"


@pytest.mark.parametrize(("method", "path"), CUSTOMER_ENDPOINTS)
async def test_valid_token_is_accepted(
    api: AsyncClient,
    google: StubGoogleClient,
    method: str,
    path: str,
) -> None:
    session = await customer_session(api, google)
    response = await api.request(method, path, headers=bearer(session["access"]))
    assert response.status_code == 200, response.text


async def test_a_refresh_token_is_not_a_bearer_token(
    api: AsyncClient, google: StubGoogleClient
) -> None:
    """Token-type confusion: the long-lived credential must not authorise calls."""
    session = await customer_session(api, google)
    response = await api.get("/api/v1/auth/me", headers=bearer(session["refresh"]))
    assert response.status_code == 401


async def test_token_signed_with_another_key_is_refused(
    api: AsyncClient, google: StubGoogleClient, auth_settings: Settings
) -> None:
    """A forged token must fail even though its claims look perfect."""
    session = await customer_session(api, google)
    me = (await api.get("/api/v1/auth/me", headers=bearer(session["access"]))).json()

    # Constructed, not `model_copy`d: copy skips validation, so the key would
    # stay a plain str where a SecretStr is expected.
    attacker_settings = Settings(
        **{**auth_settings.model_dump(exclude={"secret_key"}), "secret_key": "x" * 64}
    )
    forged, _ = create_access_token(
        settings=attacker_settings, user_id=uuid.UUID(me["id"]), role="ADMIN"
    )

    response = await api.get("/api/v1/auth/me", headers=bearer(forged))
    assert response.status_code == 401


# ------------------------------------------------- the account behind it ---


async def test_role_comes_from_the_database_not_the_token(
    api: AsyncClient, google: StubGoogleClient, auth_settings: Settings
) -> None:
    """A token claiming ADMIN gets nothing if the row says CUSTOMER.

    The claim is signed by us, so it cannot be forged — but it can be *stale*.
    Authorisation reads the row, never the claim.
    """
    session = await customer_session(api, google)
    me = (await api.get("/api/v1/auth/me", headers=bearer(session["access"]))).json()

    # A genuinely signed token that overstates the holder's role.
    settings: Settings = api._transport.app.state.settings  # type: ignore[attr-defined]
    overstated, _ = create_access_token(settings=settings, user_id=me["id"], role="ADMIN")

    response = await api.get("/api/v1/users", headers=bearer(overstated))
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "PERMISSION_DENIED"


async def test_suspension_takes_effect_on_the_next_request(
    api: AsyncClient, db_session: AsyncSession, google: StubGoogleClient
) -> None:
    """Not when the token expires — on the very next call."""
    session = await customer_session(api, google)
    assert (await api.get("/api/v1/auth/me", headers=bearer(session["access"]))).status_code == 200

    me = (await api.get("/api/v1/auth/me", headers=bearer(session["access"]))).json()
    admin = await seed_admin(db_session)
    admin_token = await sign_in_as(api, google, admin)

    suspended = await api.patch(
        f"/api/v1/users/{me['id']}/status",
        headers=bearer(admin_token),
        json={"status": "SUSPENDED", "reason": "abuse"},
    )
    assert suspended.status_code == 200, suspended.text

    after = await api.get("/api/v1/auth/me", headers=bearer(session["access"]))
    assert after.status_code == 403
    assert after.json()["error"]["code"] == "ACCOUNT_SUSPENDED"


# ---------------------------------------------------------- the session ---


async def test_sign_out_everywhere_kills_the_access_token_immediately(
    api: AsyncClient, google: StubGoogleClient
) -> None:
    """The point of the session cutoff.

    Revoking refresh tokens alone would leave this access token working for up
    to fifteen more minutes — exactly the window someone pressing "sign out
    everywhere" is trying to close.
    """
    session = await customer_session(api, google)
    assert (await api.get("/api/v1/auth/me", headers=bearer(session["access"]))).status_code == 200

    logout = await api.post("/api/v1/auth/logout-all", headers=bearer(session["access"]))
    assert logout.status_code == 204

    after = await api.get("/api/v1/auth/me", headers=bearer(session["access"]))
    assert after.status_code == 401
    assert after.json()["error"]["code"] == "SESSION_REVOKED"


async def test_sign_out_everywhere_also_kills_the_refresh_token(
    api: AsyncClient, google: StubGoogleClient
) -> None:
    session = await customer_session(api, google)
    await api.post("/api/v1/auth/logout-all", headers=bearer(session["access"]))

    refreshed = await api.post("/api/v1/auth/refresh", json={"refresh_token": session["refresh"]})
    assert refreshed.status_code == 401


async def test_signing_in_again_after_sign_out_everywhere_works(
    api: AsyncClient, google: StubGoogleClient
) -> None:
    """The cutoff must not lock the account out permanently."""
    first = await customer_session(api, google)
    await api.post("/api/v1/auth/logout-all", headers=bearer(first["access"]))

    second = await customer_session(api, google)
    response = await api.get("/api/v1/auth/me", headers=bearer(second["access"]))
    assert response.status_code == 200, response.text


async def test_one_customer_cannot_read_another_customers_booking(
    api: AsyncClient, google: StubGoogleClient
) -> None:
    """Ownership is checked against the token, not the URL.

    A 404 rather than a 403: a wrong owner must not even learn that a booking
    reference exists.
    """
    victim = await customer_session(api, google)
    victim_me = (await api.get("/api/v1/auth/me", headers=bearer(victim["access"]))).json()

    google.register(
        "google-code-other-customer",
        subject="google-sub-other",
        email=unique_email("other"),
    )
    attacker = (await sign_in_with_google(api, "google-code-other-customer"))["response"].json()

    assert victim_me["id"] != attacker["user"]["id"]

    response = await api.get(
        "/api/v1/bookings/JIVE-NOTYOURS",
        headers=bearer(attacker["access_token"]),
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "BOOKING_NOT_FOUND"
