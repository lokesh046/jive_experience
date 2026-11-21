"""End-to-end authentication, against a real database.

Google is stubbed — the backend's job is to validate the OAuth exchange and
issue its own session, and that logic is what these tests exercise.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User, UserRole, UserStatus
from tests.integration.conftest import (
    VALID_CODE,
    seed_admin,
    seed_staff,
    sign_in_with_google,
    unique_email,
    unique_phone,
)
from tests.integration.google_stub import StubGoogleClient

pytestmark = pytest.mark.integration


# ----------------------------------------------------- customer Google login ---


async def test_authorize_returns_a_google_url_and_state(api: AsyncClient) -> None:
    response = await api.get("/api/v1/auth/google/authorize")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["authorization_url"].startswith("https://accounts.google.com/")
    assert len(body["state"]) >= 20


async def test_first_sign_in_creates_the_customer(api: AsyncClient, customer_email: str) -> None:
    result = await sign_in_with_google(api)
    response = result["response"]

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"] and body["refresh_token"]
    assert body["user"]["role"] == "CUSTOMER"
    assert body["user"]["email"] == customer_email
    assert body["user"]["phone_e164"] is None, "phone is collected after sign-in"


async def test_second_sign_in_reuses_the_same_account(
    api: AsyncClient, google: StubGoogleClient, customer_email: str
) -> None:
    first = (await sign_in_with_google(api))["response"].json()

    google.register(
        "google-auth-code-second", subject=first["user"]["id"] and "ignored", email=customer_email
    )
    # Same Google subject as the first sign-in.
    google.identities["google-auth-code-second"] = google.identities[VALID_CODE]
    second = (await sign_in_with_google(api, "google-auth-code-second"))["response"].json()

    assert first["user"]["id"] == second["user"]["id"]


async def test_callback_without_a_valid_state_is_refused(api: AsyncClient) -> None:
    """Login CSRF: a callback we did not start must not sign anyone in."""
    response = await api.post(
        "/api/v1/auth/google/callback",
        json={"code": VALID_CODE, "state": "a-state-we-never-issued"},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "OAUTH_STATE_INVALID"


async def test_state_is_single_use(api: AsyncClient, google: StubGoogleClient) -> None:
    """Replaying a whole callback must fail even with a real state."""
    result = await sign_in_with_google(api)
    assert result["response"].status_code == 200

    replay = await api.post(
        "/api/v1/auth/google/callback",
        json={"code": VALID_CODE, "state": result["state"]},
    )
    assert replay.status_code == 401
    assert replay.json()["error"]["code"] == "OAUTH_STATE_INVALID"


async def test_invalid_authorization_code_is_rejected(api: AsyncClient) -> None:
    result = await sign_in_with_google(api, "a-code-google-never-issued")

    assert result["response"].status_code == 401
    assert result["response"].json()["error"]["code"] == "GOOGLE_CODE_INVALID"


async def test_unverified_google_email_is_refused(
    api: AsyncClient, google: StubGoogleClient
) -> None:
    """An unverified address could belong to someone else, which would let an
    attacker claim an existing account by email."""
    google.register(
        "google-code-unverified",
        subject="google-sub-unverified",
        email=unique_email("unverified"),
        email_verified=False,
    )

    result = await sign_in_with_google(api, "google-code-unverified")

    assert result["response"].status_code == 401
    assert result["response"].json()["error"]["code"] == "GOOGLE_EMAIL_UNVERIFIED"


async def test_signing_in_as_a_staff_email_yields_the_staff_role(
    api: AsyncClient, google: StubGoogleClient, db_session: AsyncSession
) -> None:
    """A pre-provisioned staff email signs in as staff, not as a customer."""
    staff = await seed_staff(db_session)

    google.register("google-code-staff-email", subject="google-sub-staff", email=staff.email)
    result = await sign_in_with_google(api, "google-code-staff-email")

    # Signing in as a staff email is now the *supported* path, not a refusal:
    # the role comes from the pre-provisioned row.
    assert result["response"].status_code == 200
    assert result["response"].json()["user"]["role"] == "EVENT_STAFF"


# ------------------------------------------------------------ phone number ---


async def test_customer_can_attach_a_phone_number(api: AsyncClient) -> None:
    issued = (await sign_in_with_google(api))["response"].json()
    phone = unique_phone()

    response = await api.put(
        "/api/v1/auth/phone",
        headers={"Authorization": f"Bearer {issued['access_token']}"},
        json={"phone_e164": phone},
    )

    assert response.status_code == 200, response.text
    assert response.json()["phone_e164"] == phone


async def test_phone_from_a_blocked_country_is_refused(api: AsyncClient) -> None:
    issued = (await sign_in_with_google(api))["response"].json()

    response = await api.put(
        "/api/v1/auth/phone",
        headers={"Authorization": f"Bearer {issued['access_token']}"},
        json={"phone_e164": "+14155550100"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "PHONE_COUNTRY_NOT_ALLOWED"


async def test_a_phone_number_cannot_be_claimed_twice(
    api: AsyncClient, db_session: AsyncSession
) -> None:
    """Scalper control: one phone number, one account."""
    phone = unique_phone()
    db_session.add(
        User(
            role=UserRole.CUSTOMER,
            status=UserStatus.ACTIVE,
            email=unique_email("existing"),
            phone_e164=phone,
        )
    )
    await db_session.flush()

    issued = (await sign_in_with_google(api))["response"].json()
    response = await api.put(
        "/api/v1/auth/phone",
        headers={"Authorization": f"Bearer {issued['access_token']}"},
        json={"phone_e164": phone},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "PHONE_TAKEN"


async def test_malformed_phone_number_is_rejected(api: AsyncClient) -> None:
    issued = (await sign_in_with_google(api))["response"].json()

    response = await api.put(
        "/api/v1/auth/phone",
        headers={"Authorization": f"Bearer {issued['access_token']}"},
        json={"phone_e164": "9876543210"},
    )

    assert response.status_code == 422


# ---------------------------------------------- privileged sign-in via Google ---


async def test_preprovisioned_admin_signs_in_with_google_and_keeps_the_role(
    api: AsyncClient, google: StubGoogleClient, db_session: AsyncSession
) -> None:
    """The whole permission model, in one test.

    An administrator's row is created first with no Google identity. When they
    sign in with Google under that email, they are linked to the existing row
    and keep ADMIN — they are not created as a new customer.
    """
    admin = await seed_admin(db_session)
    assert admin.google_sub is None, "not yet linked to a Google identity"

    google.register(
        "google-code-admin-first-signin",
        subject="google-sub-admin-1",
        email=admin.email,
        full_name="Ops Admin",
    )
    result = await sign_in_with_google(api, "google-code-admin-first-signin")

    assert result["response"].status_code == 200, result["response"].text
    body = result["response"].json()
    assert body["user"]["role"] == "ADMIN"
    assert body["user"]["id"] == str(admin.id), "linked, not duplicated"


async def test_staff_sign_in_keeps_the_staff_role(
    api: AsyncClient, google: StubGoogleClient, db_session: AsyncSession
) -> None:
    staff = await seed_staff(db_session)
    google.register("google-code-staff-signin", subject="google-sub-staff-1", email=staff.email)

    result = await sign_in_with_google(api, "google-code-staff-signin")

    assert result["response"].json()["user"]["role"] == "EVENT_STAFF"


async def test_an_unknown_google_account_becomes_a_customer_never_an_admin(
    api: AsyncClient, google: StubGoogleClient
) -> None:
    """Signing in must never grant authority.

    Anyone in the world can present a valid Google token. The only role that
    path can produce is CUSTOMER.
    """
    google.register(
        "google-code-stranger",
        subject="google-sub-stranger",
        email=unique_email("stranger"),
    )

    result = await sign_in_with_google(api, "google-code-stranger")

    assert result["response"].json()["user"]["role"] == "CUSTOMER"


async def test_suspended_admin_cannot_sign_in(
    api: AsyncClient, google: StubGoogleClient, db_session: AsyncSession
) -> None:
    admin = await seed_admin(db_session)
    admin.status = UserStatus.SUSPENDED
    await db_session.flush()

    google.register(
        "google-code-suspended-admin",
        subject="google-sub-suspended",
        email=admin.email,
    )
    result = await sign_in_with_google(api, "google-code-suspended-admin")

    assert result["response"].status_code == 403
    assert result["response"].json()["error"]["code"] == "ACCOUNT_SUSPENDED"


async def test_there_is_no_password_login_endpoint(api: AsyncClient) -> None:
    """Password login is gone, not merely unused.

    Leaving a disabled endpoint behind is how a credential path quietly comes
    back; this asserts the route does not exist at all.
    """
    response = await api.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "anything"},
    )
    assert response.status_code == 404


# ------------------------------------------------------- refresh and logout ---


async def test_refresh_returns_a_new_pair_and_retires_the_old_token(
    api: AsyncClient,
) -> None:
    issued = (await sign_in_with_google(api))["response"].json()

    refreshed = await api.post(
        "/api/v1/auth/refresh", json={"refresh_token": issued["refresh_token"]}
    )

    assert refreshed.status_code == 200, refreshed.text
    body = refreshed.json()
    assert body["refresh_token"] != issued["refresh_token"], "token must rotate"
    assert body["user"]["id"] == issued["user"]["id"]


async def test_replaying_a_rotated_token_kills_the_whole_session_family(
    api: AsyncClient,
) -> None:
    """Reuse detection.

    If an old refresh token is presented again, it leaked. Both the thief and
    the legitimate holder are signed out, which is the correct outcome — the
    real user re-authenticates, the thief cannot.
    """
    issued = (await sign_in_with_google(api))["response"].json()
    rotated = (
        await api.post("/api/v1/auth/refresh", json={"refresh_token": issued["refresh_token"]})
    ).json()

    replay = await api.post("/api/v1/auth/refresh", json={"refresh_token": issued["refresh_token"]})
    assert replay.status_code == 401
    assert replay.json()["error"]["code"] == "REFRESH_REUSED"

    # The token issued to the legitimate user is now dead too.
    after = await api.post("/api/v1/auth/refresh", json={"refresh_token": rotated["refresh_token"]})
    assert after.status_code == 401


async def test_unknown_refresh_token_is_rejected(api: AsyncClient) -> None:
    response = await api.post("/api/v1/auth/refresh", json={"refresh_token": "x" * 64})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "REFRESH_INVALID"


async def test_logout_invalidates_the_refresh_token(api: AsyncClient) -> None:
    issued = (await sign_in_with_google(api))["response"].json()

    logout = await api.post("/api/v1/auth/logout", json={"refresh_token": issued["refresh_token"]})
    assert logout.status_code == 204

    reuse = await api.post("/api/v1/auth/refresh", json={"refresh_token": issued["refresh_token"]})
    assert reuse.status_code == 401


async def test_logout_with_an_unknown_token_still_succeeds(api: AsyncClient) -> None:
    """Logout must not be an oracle for which tokens exist."""
    response = await api.post("/api/v1/auth/logout", json={"refresh_token": "y" * 64})
    assert response.status_code == 204
