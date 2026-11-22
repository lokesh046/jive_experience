"""Add event_performers: the lineup shown on an event page.

Revision ID: c41e7a9d2b60
Revises: 9bfdf4b0680d
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c41e7a9d2b60"
down_revision: str | None = "9bfdf4b0680d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "event_performers",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "event_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("events.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("role", sa.String(200)),
        sa.Column("photo_url", sa.String(1024)),
        sa.Column("performs_at", sa.DateTime(timezone=True)),
        sa.Column("sort_order", sa.Integer, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ix_event_performers_event_id_sort_order", "event_performers", ["event_id", "sort_order"]
    )
    op.create_index("ix_event_performers_created_at", "event_performers", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_event_performers_created_at", table_name="event_performers")
    op.drop_index("ix_event_performers_event_id_sort_order", table_name="event_performers")
    op.drop_table("event_performers")
