"""Add artists: the people shown on the homepage.

Revision ID: e3b7c1d8f205
Revises: d29a5b0c6e74
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e3b7c1d8f205"
down_revision: str | None = "d29a5b0c6e74"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "artists",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("note", sa.String(200)),
        sa.Column("photo_url", sa.String(1024)),
        sa.Column("show_on_home", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("char_length(btrim(name)) > 0", name=op.f("ck_artists_name_not_blank")),
    )
    op.create_index("ix_artists_show_on_home_sort_order", "artists", ["show_on_home", "sort_order"])
    op.create_index("ix_artists_created_at", "artists", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_artists_created_at", table_name="artists")
    op.drop_index("ix_artists_show_on_home_sort_order", table_name="artists")
    op.drop_table("artists")
