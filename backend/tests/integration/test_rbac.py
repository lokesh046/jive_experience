"""Role boundaries and account-state enforcement.

Every one of these is a question an attacker will ask, so each gets a test.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import UserStatus
from tests.integration.conftest import (
    seed_admin,
    sign_in_as,
    sign_in_with_google,
    unique_email,
)
from tests.integration.google_stub import StubGoogleClient

pytestmark = pytest.mark.integration

ADMIN_ONLY_ENDPOINTS = [
    ("GET", "/api/v1/users"),
    ("POST", "/api/v1/users/staff"),
]


async def customer_token(api: AsyncClient) -> str:
    """A fresh Google account signs in; it can only ever be a CUSTOMER."""
    result = await sign_in_with_google(api)
    return str(result["response"].json()["access_token"])


async def admin_token(api: AsyncClient, session: AsyncSession, google: StubGoogleClient) -> str:
    """Sign in a pre-provisioned administrator through Google."""
    admin = await seed_admin(session)
    return await sign_in_as(api, google, admin)


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ------------------------------------------------------------ unauthenticated ---


@pytest.mark.parametrize(("method", "path"), ADMIN_ONLY_ENDPOINTS)
async def test_admin_endpoints_require_authentication(
    api: AsyncClient, method: str, path: str
) -> None:
    response = await api.request(method, path, json={})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


async def test_profile_requires_authentication(api: AsyncClient) -> None:
    assert (await api.get("/api/v1/users/me")).status_code == 401


async def test_malformed_bearer_token_is_rejected(api: AsyncClient) -> None:
    response = await api.get("/api/v1/users/me", headers=bearer("not-a-real-token"))
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "TOKEN_INVALID"


# --------------------------------------------------------------- wrong role ---


@pytest.mark.parametrize(("method", "path"), ADMIN_ONLY_ENDPOINTS)
async def test_customer_cannot_reach_admin_endpoints(
    api: AsyncClient, method: str, path: str
) -> None:
    token = await customer_token(api)

    response = await api.request(method, path, headers=bearer(token), json={})

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "PERMISSION_DENIED"


async def test_customer_cannot_create_a_staff_account(api: AsyncClient) -> None:
    """The privilege-escalation path that matters most."""
    token = await customer_token(api)

    response = await api.post(
        "/api/v1/users/staff",
        headers=bearer(token),
        json={
            "email": unique_email("attacker"),
            "full_name": "Attacker",
            "role": "ADMIN",
        },
    )

    assert response.status_code == 403


async def test_customer_cannot_suspend_another_account(
    api: AsyncClient, db_session: AsyncSession, google: StubGoogleClient
) -> None:
    admin = await seed_admin(db_session)
    token = await customer_token(api)

    response = await api.patch(
        f"/api/v1/users/{admin.id}/status",
        headers=bearer(token),
        json={"status": "SUSPENDED"},
    )

    assert response.status_code == 403


# ------------------------------------------------------------ correct role ---


async def test_admin_can_list_users(
    api: AsyncClient, db_session: AsyncSession, google: StubGoogleClient
) -> None:
    token = await admin_token(api, db_session, google)

    response = await api.get("/api/v1/users", headers=bearer(token))

    assert response.status_code == 200, response.text
    body = response.json()
    assert "items" in body and "total" in body


async def test_admin_can_grant_staff_access(
    api: AsyncClient, db_session: AsyncSession, google: StubGoogleClient
) -> None:
    token = await admin_token(api, db_session, google)

    scanner_email = unique_email("scanner")
    created = await api.post(
        "/api/v1/users/staff",
        headers=bearer(token),
        json={
            "email": scanner_email,
            "full_name": "Gate Scanner",
            "role": "EVENT_STAFF",
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["role"] == "EVENT_STAFF"


async def test_staff_account_cannot_be_created_with_the_customer_role(
    api: AsyncClient, db_session: AsyncSession, google: StubGoogleClient
) -> None:
    token = await admin_token(api, db_session, google)

    response = await api.post(
        "/api/v1/users/staff",
        headers=bearer(token),
        json={
            "email": unique_email("weird"),
            "full_name": "Weird",
            "role": "CUSTOMER",
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_admin_cannot_suspend_themselves(
    api: AsyncClient, db_session: AsyncSession, google: StubGoogleClient
) -> None:
    """Locking the only administrator out of the dashboard is unrecoverable
    without server access."""
    token = await admin_token(api, db_session, google)
    me = await api.get("/api/v1/auth/me", headers=bearer(token))
    own_id = me.json()["id"]

    response = await api.patch(
        f"/api/v1/users/{own_id}/status",
        headers=bearer(token),
        json={"status": "SUSPENDED"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "CANNOT_MODIFY_SELF"


async def test_suspending_an_account_ends_its_sessions_immediately(
    api: AsyncClient, db_session: AsyncSession, google: StubGoogleClient
) -> None:
    """A suspended user must not keep working until their access token expires."""
    customer = await customer_token(api)
    me = await api.get("/api/v1/auth/me", headers=bearer(customer))
    customer_id = me.json()["id"]

    admin = await admin_token(api, db_session, google)
    suspended = await api.patch(
        f"/api/v1/users/{customer_id}/status",
        headers=bearer(admin),
        json={"status": "SUSPENDED", "reason": "chargeback abuse"},
    )
    assert suspended.status_code == 200, suspended.text

    after = await api.get("/api/v1/auth/me", headers=bearer(customer))
    assert after.status_code == 403
    assert after.json()["error"]["code"] == "ACCOUNT_SUSPENDED"


async def test_suspension_is_recorded_in_the_audit_trail(
    api: AsyncClient, db_session: AsyncSession, google: StubGoogleClient
) -> None:
    import sqlalchemy as sa

    customer = await customer_token(api)
    customer_id = (await api.get("/api/v1/auth/me", headers=bearer(customer))).json()["id"]
    admin = await admin_token(api, db_session, google)

    await api.patch(
        f"/api/v1/users/{customer_id}/status",
        headers=bearer(admin),
        json={"status": "SUSPENDED", "reason": "chargeback abuse"},
    )

    row = (
        await db_session.execute(
            sa.text(
                "SELECT action, entity_id, after FROM audit_logs "
                "WHERE action = 'user.status_changed' ORDER BY created_at DESC LIMIT 1"
            )
        )
    ).first()

    assert row is not None, "a suspension must leave an audit record"
    assert row.entity_id == customer_id
    assert row.after["status"] == "SUSPENDED"


async def test_unknown_user_id_returns_not_found(
    api: AsyncClient, db_session: AsyncSession, google: StubGoogleClient
) -> None:
    token = await admin_token(api, db_session, google)

    response = await api.patch(
        f"/api/v1/users/{uuid.uuid4()}/status",
        headers=bearer(token),
        json={"status": UserStatus.SUSPENDED.value},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"
