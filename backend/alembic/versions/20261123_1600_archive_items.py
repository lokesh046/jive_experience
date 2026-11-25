"""Add archive_items: the photos of past nights shown on the homepage.

Revision ID: f4c8d2e9a316
Revises: e3b7c1d8f205
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f4c8d2e9a316"
down_revision: str | None = "e3b7c1d8f205"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "archive_items",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("caption", sa.String(200)),
        sa.Column("photo_url", sa.String(1024), nullable=False),
        sa.Column("show_on_home", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "char_length(btrim(photo_url)) > 0", name=op.f("ck_archive_items_photo_not_blank")
        ),
    )
    op.create_index(
        "ix_archive_items_show_on_home_sort_order", "archive_items", ["show_on_home", "sort_order"]
    )
    op.create_index("ix_archive_items_created_at", "archive_items", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_archive_items_created_at", table_name="archive_items")
    op.drop_index("ix_archive_items_show_on_home_sort_order", table_name="archive_items")
    op.drop_table("archive_items")
