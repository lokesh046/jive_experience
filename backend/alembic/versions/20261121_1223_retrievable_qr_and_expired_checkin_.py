"""Add the EXPIRED check-in result.

A ticket is valid from purchase until the event finishes. Scanning one
afterwards is operationally different from a forged code or a double scan, so
it gets its own result rather than being folded into INVALID — the person at
the gate needs to know whether to send someone to the box office or call
security.

Revision ID: 9bfdf4b0680d
Revises: 95a77b29760c
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9bfdf4b0680d"
down_revision: str | None = "95a77b29760c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # PostgreSQL 12+ permits this inside a transaction; the new value simply
    # cannot be *used* until that transaction commits, which nothing here does.
    op.execute(sa.text("ALTER TYPE checkin_result ADD VALUE IF NOT EXISTS 'EXPIRED'"))


def downgrade() -> None:
    # PostgreSQL cannot drop a value from an enum. Removing it would mean
    # rebuilding the type and rewriting every row referencing it — far more
    # destructive than leaving one unused label in place.
    pass
