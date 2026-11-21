"""The database — not only the application — enforces the identity rules.

These constraints are the last line of defence against a privileged account
being created through the public Google sign-in path, so they are tested
directly against PostgreSQL rather than through the ORM.
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from tests.integration.conftest import unique_email, unique_phone

pytestmark = pytest.mark.integration

INSERT = sa.text(
    """
    INSERT INTO users (role, status, email, phone_e164, google_sub)
    VALUES (:role, 'ACTIVE', :email, :phone, :google_sub)
    RETURNING id
    """
)


async def _insert(
    conn: AsyncConnection,
    *,
    role: str,
    email: str | None = None,
    phone: str | None = None,
    google_sub: str | None = None,
) -> uuid.UUID:
    """Insert inside a SAVEPOINT.

    PostgreSQL aborts the entire transaction on a constraint violation, so a
    test that expects several rejections must isolate each attempt; otherwise
    every statement after the first failure reports "current transaction is
    aborted" instead of the constraint actually being exercised.
    """
    async with conn.begin_nested():
        result = await conn.execute(
            INSERT,
            {
                "role": role,
                "email": email if email is not None else unique_email(),
                "phone": phone,
                "google_sub": google_sub or uuid.uuid4().hex,
            },
        )
        return result.scalar_one()  # type: ignore[no-any-return]


# ------------------------------------------------------------ valid rows ---


async def test_google_customer_is_accepted(db_connection: AsyncConnection) -> None:
    """A customer has an email and no password — that is the whole rule."""
    user_id = await _insert(db_connection, role="CUSTOMER")
    assert isinstance(user_id, uuid.UUID)


async def test_customer_may_have_no_phone_number_at_sign_up(
    db_connection: AsyncConnection,
) -> None:
    """The phone is collected after sign-in, and required before booking."""
    assert await _insert(db_connection, role="CUSTOMER", phone=None)


async def test_customer_may_add_a_phone_number(db_connection: AsyncConnection) -> None:
    assert await _insert(db_connection, role="CUSTOMER", phone=unique_phone())


@pytest.mark.parametrize("role", ["ADMIN", "EVENT_STAFF"])
async def test_privileged_account_needs_nothing_but_an_email(
    db_connection: AsyncConnection, role: str
) -> None:
    """Privileged rows carry no credential at all.

    Authority is the role on the row; the credential is the person's Google
    account, which this system never stores anything about beyond the subject
    identifier.
    """
    assert await _insert(db_connection, role=role)


# --------------------------------------------------------- rejected rows ---


async def test_every_account_must_have_an_email(db_connection: AsyncConnection) -> None:
    """Email is the shared identity across both sign-in paths, so it is
    NOT NULL. Inserted directly: the helper substitutes a default."""
    with pytest.raises(IntegrityError):
        async with db_connection.begin_nested():
            await db_connection.execute(
                sa.text(
                    "INSERT INTO users (role, status, email) VALUES ('CUSTOMER', 'ACTIVE', NULL)"
                )
            )


@pytest.mark.parametrize(
    "phone", ["9876543210", "+0987654321", "+91 98765 43210", "+91-9876543210", "abc"]
)
async def test_phone_must_be_e164(db_connection: AsyncConnection, phone: str) -> None:
    with pytest.raises(IntegrityError, match="phone_is_e164"):
        await _insert(db_connection, role="CUSTOMER", phone=phone)


async def test_phone_numbers_are_unique(db_connection: AsyncConnection) -> None:
    """One phone number, one account — the per-account purchase limit depends
    on this being true."""
    phone = unique_phone()
    await _insert(db_connection, role="CUSTOMER", phone=phone)
    with pytest.raises(IntegrityError, match="uq_users_phone_e164"):
        await _insert(db_connection, role="CUSTOMER", phone=phone)


async def test_email_addresses_are_unique(db_connection: AsyncConnection) -> None:
    email = unique_email()
    await _insert(db_connection, role="CUSTOMER", email=email)
    with pytest.raises(IntegrityError, match="uq_users_email"):
        await _insert(db_connection, role="CUSTOMER", email=email)


async def test_google_subjects_are_unique(db_connection: AsyncConnection) -> None:
    """Two accounts must never map to the same Google identity."""
    subject = uuid.uuid4().hex
    await _insert(db_connection, role="CUSTOMER", google_sub=subject)
    with pytest.raises(IntegrityError, match="uq_users_google_sub"):
        await _insert(db_connection, role="CUSTOMER", google_sub=subject)


# ------------------------------------------------------------- behaviour ---


async def test_timestamps_are_timezone_aware(db_connection: AsyncConnection) -> None:
    email = unique_email()
    await _insert(db_connection, role="CUSTOMER", email=email)
    created_at = (
        await db_connection.execute(
            sa.text("SELECT created_at FROM users WHERE email = :email"), {"email": email}
        )
    ).scalar_one()
    assert created_at.tzinfo is not None


async def test_deleting_a_user_cascades_to_sessions_but_keeps_the_audit_trail(
    db_connection: AsyncConnection,
) -> None:
    user_id = await _insert(db_connection, role="CUSTOMER")

    await db_connection.execute(
        sa.text(
            "INSERT INTO refresh_tokens (user_id, token_hash, family_id, expires_at) "
            "VALUES (:uid, :hash, gen_random_uuid(), now() + interval '30 days')"
        ),
        {"uid": user_id, "hash": uuid.uuid4().hex * 2},
    )
    await db_connection.execute(
        sa.text(
            "INSERT INTO audit_logs (actor_user_id, action, entity_type, entity_id) "
            "VALUES (:uid, 'event.published', 'event', :eid)"
        ),
        {"uid": user_id, "eid": str(uuid.uuid4())},
    )

    await db_connection.execute(sa.text("DELETE FROM users WHERE id = :uid"), {"uid": user_id})

    tokens = (
        await db_connection.execute(
            sa.text("SELECT count(*) FROM refresh_tokens WHERE user_id = :uid"), {"uid": user_id}
        )
    ).scalar_one()
    audits = (
        await db_connection.execute(
            sa.text("SELECT count(*) FROM audit_logs WHERE actor_user_id IS NULL")
        )
    ).scalar_one()

    assert tokens == 0, "sessions must not outlive the account"
    assert audits >= 1, "the audit trail must survive the account it refers to"
