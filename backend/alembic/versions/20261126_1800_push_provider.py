"""Let a push device be a phone as well as a browser.

Revision ID: f0c5d8e3a972
Revises: e9b4c7d2f861
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f0c5d8e3a972"
down_revision: str | None = "e9b4c7d2f861"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "push_subscriptions",
        sa.Column("provider", sa.String(length=20), nullable=False, server_default="webpush"),
    )


def downgrade() -> None:
    op.drop_column("push_subscriptions", "provider")
