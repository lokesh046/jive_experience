"""Sign in with a one-time code emailed to the address, next to Google sign-in."""

from __future__ import annotations

import secrets

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.conftest import seed_admin, unique_email

pytestmark = pytest.mark.integration

REQUEST = "/api/v1/auth/email/request"
VERIFY = "/api/v1/auth/email/verify"


@pytest.fixture(autouse=True)
def known_code(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setattr(secrets, "randbelow", lambda _n: 123456)
    return "123456"


async def test_a_new_address_gets_a_customer_account_and_the_code_works_once(
    api: AsyncClient, db_session: AsyncSession, known_code: str
) -> None:
    email = unique_email("otp")
    asked = await api.post(REQUEST, json={"email": email.upper()})
    assert asked.status_code == 202

    ok = await api.post(VERIFY, json={"email": email, "code": known_code})
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["user"]["role"] == "CUSTOMER" and body["user"]["email"] == email.lower()
    assert body["access_token"] and body["refresh_token"]
    verified = (
        await db_session.execute(
            sa.text("SELECT email_verified_at IS NOT NULL FROM users WHERE email = :e"),
            {"e": email.lower()},
        )
    ).scalar_one()
    assert verified is True

    again = await api.post(VERIFY, json={"email": email, "code": known_code})
    assert again.status_code == 401 and again.json()["error"]["code"] == "OTP_INVALID"


async def test_five_wrong_tries_burn_the_code(api: AsyncClient, known_code: str) -> None:
    email = unique_email("burn")
    await api.post(REQUEST, json={"email": email})
    for _ in range(5):
        wrong = await api.post(VERIFY, json={"email": email, "code": "000000"})
        assert wrong.status_code == 401
    # The right code no longer works: someone guessing cannot walk through all million.
    late = await api.post(VERIFY, json={"email": email, "code": known_code})
    assert late.status_code == 401 and late.json()["error"]["code"] == "OTP_INVALID"


async def test_a_code_cannot_be_used_for_another_address(api: AsyncClient, known_code: str) -> None:
    mine, theirs = unique_email("mine"), unique_email("theirs")
    await api.post(REQUEST, json={"email": mine})
    stolen = await api.post(VERIFY, json={"email": theirs, "code": known_code})
    assert stolen.status_code == 401


async def test_an_existing_admin_signs_in_with_the_role_they_already_have(
    api: AsyncClient, db_session: AsyncSession, known_code: str
) -> None:
    admin = await seed_admin(db_session)
    email = admin.email
    await db_session.commit()
    await api.post(REQUEST, json={"email": email})
    ok = await api.post(VERIFY, json={"email": email, "code": known_code})
    assert ok.status_code == 200 and ok.json()["user"]["role"] == "ADMIN"


async def test_asking_again_inside_a_minute_does_not_replace_the_code(
    api: AsyncClient, monkeypatch: pytest.MonkeyPatch, known_code: str
) -> None:
    email = unique_email("cool")
    await api.post(REQUEST, json={"email": email})
    monkeypatch.setattr(secrets, "randbelow", lambda _n: 654321)
    second = await api.post(REQUEST, json={"email": email})
    assert second.status_code == 202  # same answer, nothing new sent
    assert (await api.post(VERIFY, json={"email": email, "code": "654321"})).status_code == 401
    assert (await api.post(VERIFY, json={"email": email, "code": known_code})).status_code == 200


async def test_a_suspended_account_gets_the_same_answer_but_no_code(
    api: AsyncClient, db_session: AsyncSession, known_code: str
) -> None:
    email = unique_email("susp")
    await db_session.execute(
        sa.text(
            "INSERT INTO users (id, role, status, email) "
            "VALUES (gen_random_uuid(), 'CUSTOMER', 'SUSPENDED', :e)"
        ),
        {"e": email},
    )
    await db_session.commit()
    asked = await api.post(REQUEST, json={"email": email})
    assert asked.status_code == 202
    assert (await api.post(VERIFY, json={"email": email, "code": known_code})).status_code == 401


async def test_badly_formed_input_is_refused(api: AsyncClient) -> None:
    assert (await api.post(REQUEST, json={"email": "nope"})).status_code == 422
    bad = await api.post(VERIFY, json={"email": unique_email("x"), "code": "12ab56"})
    assert bad.status_code == 422
