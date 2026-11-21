"""Switch customer identity from Firebase phone OTP to Google OAuth 2.0.

Customers now sign in with Google, so:

* `firebase_uid` is replaced by `google_sub` — Google's stable subject
  identifier, which (unlike the email address) never changes for an account.
* `email` becomes NOT NULL: it is now the shared identity across both the
  OAuth path and the admin/staff password path.
* `phone_e164` becomes optional. Google accounts are free and unlimited, so a
  verified phone is collected after sign-in and required before a reservation
  — see docs/anti-bot.md.

The CHECK constraints are rewritten to match. They are the reason a privileged
account still cannot be created through the public sign-in path: that path sets
no password hash, and `privileged_has_password` rejects the row.

**Alembic autogenerate does not detect CHECK constraint changes.** Those
statements are written by hand here, and `alembic check` will not warn if they
are forgotten — the constraint tests in the integration suite are what catch it.

Every constraint name is wrapped in `op.f(...)`. Without it the metadata naming
convention is applied a second time and emits
`ck_users_ck_users_customer_has_no_password`.

This migration refuses to run if any account has no email address, rather than
inventing a placeholder identity for a real person.

Revision ID: 890335c892c1
Revises: 274b3ece4c19
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "890335c892c1"
down_revision: str | None = "274b3ece4c19"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CUSTOMER_NO_PASSWORD = "(role <> 'CUSTOMER') OR (password_hash IS NULL)"
PRIVILEGED_HAS_PASSWORD = "(role = 'CUSTOMER') OR (password_hash IS NOT NULL)"

OLD_CUSTOMER_CHECK = "(role <> 'CUSTOMER') OR (phone_e164 IS NOT NULL AND password_hash IS NULL)"
OLD_PRIVILEGED_CHECK = "(role = 'CUSTOMER') OR (email IS NOT NULL AND password_hash IS NOT NULL)"


def upgrade() -> None:
    # The old constraints reference columns whose nullability is about to
    # change, so they come off first.
    op.drop_constraint(op.f("ck_users_customer_has_phone_and_no_password"), "users", type_="check")
    op.drop_constraint(op.f("ck_users_privileged_has_email_and_password"), "users", type_="check")

    op.add_column("users", sa.Column("google_sub", sa.String(length=255), nullable=True))
    op.add_column("users", sa.Column("avatar_url", sa.String(length=512), nullable=True))
    op.create_unique_constraint(op.f("uq_users_google_sub"), "users", ["google_sub"])

    without_email = op.get_bind().scalar(sa.text("SELECT count(*) FROM users WHERE email IS NULL"))
    if without_email:
        raise RuntimeError(
            f"{without_email} account(s) have no email address, which Google "
            "sign-in requires. Resolve those rows before migrating."
        )
    op.alter_column("users", "email", existing_type=sa.String(length=320), nullable=False)

    op.drop_column("users", "firebase_uid")

    op.create_check_constraint(
        op.f("ck_users_customer_has_no_password"), "users", CUSTOMER_NO_PASSWORD
    )
    op.create_check_constraint(
        op.f("ck_users_privileged_has_password"), "users", PRIVILEGED_HAS_PASSWORD
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_users_privileged_has_password"), "users", type_="check")
    op.drop_constraint(op.f("ck_users_customer_has_no_password"), "users", type_="check")

    op.add_column("users", sa.Column("firebase_uid", sa.String(length=128), nullable=True))
    op.create_unique_constraint(op.f("uq_users_firebase_uid"), "users", ["firebase_uid"])

    op.alter_column("users", "email", existing_type=sa.String(length=320), nullable=True)

    op.drop_constraint(op.f("uq_users_google_sub"), "users", type_="unique")
    op.drop_column("users", "avatar_url")
    op.drop_column("users", "google_sub")

    # The old customer rule demanded a phone number, which accounts created
    # under Google sign-in do not have. Those rows are removed rather than
    # left to violate the constraint being restored.
    op.execute(sa.text("DELETE FROM users WHERE role = 'CUSTOMER' AND phone_e164 IS NULL"))

    op.create_check_constraint(
        op.f("ck_users_customer_has_phone_and_no_password"), "users", OLD_CUSTOMER_CHECK
    )
    op.create_check_constraint(
        op.f("ck_users_privileged_has_email_and_password"), "users", OLD_PRIVILEGED_CHECK
    )
