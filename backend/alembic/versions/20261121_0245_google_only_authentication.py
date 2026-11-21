"""Remove passwords: every account signs in with Google OAuth 2.0.

Administrators and event staff previously signed in with email + password.
They now use the same Google flow as customers, so:

* `password_hash` and `password_changed_at` are dropped;
* the CHECK constraints that required a password for privileged roles, and
  forbade one for customers, are dropped with them.

**Authorisation did not move into the credential — it moved into the row.** A
privileged account exists because an administrator created it with that email
and role before the person first signed in; the verified Google email is what
links them. No sign-in path can grant a role.

Autogenerate does not detect CHECK constraint changes, so those drops are
written by hand. Constraint names are wrapped in `op.f(...)`, without which
the metadata naming convention is applied twice.

Operational note on `downgrade()`: the columns come back nullable, but no hash
can be restored — the hashes are gone. The old CHECK constraints are recreated
`NOT VALID`, which restores the schema shape (so the preceding migration can
still drop them by name) while skipping validation of existing rows. Without
that, `privileged_has_password` would reject every administrator the moment it
was added back. Restoring password login for real means backfilling hashes and
then running `VALIDATE CONSTRAINT`.

Revision ID: 601f1aecb6e8
Revises: c5b2edd2f5ef
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "601f1aecb6e8"
down_revision: str | None = "c5b2edd2f5ef"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(op.f("ck_users_customer_has_no_password"), "users", type_="check")
    op.drop_constraint(op.f("ck_users_privileged_has_password"), "users", type_="check")

    op.drop_column("users", "password_changed_at")
    op.drop_column("users", "password_hash")


def downgrade() -> None:
    op.add_column("users", sa.Column("password_hash", sa.String(length=255), nullable=True))
    op.add_column(
        "users",
        sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Recreated NOT VALID: every privileged row now has a NULL password, so a
    # validating constraint would be rejected outright. NOT VALID applies the
    # rule to new rows only, which restores the schema shape without
    # invalidating the data that exists.
    op.execute(
        sa.text(
            "ALTER TABLE users ADD CONSTRAINT ck_users_customer_has_no_password "
            "CHECK ((role <> 'CUSTOMER') OR (password_hash IS NULL)) NOT VALID"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE users ADD CONSTRAINT ck_users_privileged_has_password "
            "CHECK ((role = 'CUSTOMER') OR (password_hash IS NOT NULL)) NOT VALID"
        )
    )
