"""Add site_settings: administrator-editable settings such as the default refund policy.

Revision ID: f85c1d6e2a39
Revises: e63a9c4d1f28
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f85c1d6e2a39"
down_revision: str | None = "e63a9c4d1f28"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "site_settings",
        sa.Column("key", sa.String(80), primary_key=True),
        sa.Column("value", postgresql.JSONB(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
    )


def downgrade() -> None:
    op.drop_table("site_settings")
