"""Add waitlist_entries.

Revision ID: c18f4a9b5d63
Revises: b07e3f8a4c52
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c18f4a9b5d63"
down_revision: str | None = "b07e3f8a4c52"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATUSES = ("WAITING", "NOTIFIED", "LEFT")


def upgrade() -> None:
    postgresql.ENUM(*STATUSES, name="waitlist_status").create(op.get_bind(), checkfirst=True)
    op.create_table(
        "waitlist_entries",
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
        sa.Column(
            "ticket_category_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ticket_categories.id", ondelete="SET NULL"),
        ),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "status",
            postgresql.ENUM(*STATUSES, name="waitlist_status", create_type=False),
            nullable=False,
            server_default="WAITING",
        ),
        sa.Column("leave_token", sa.String(64), nullable=False, unique=True),
        sa.Column("notified_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("event_id", "email", name="uq_waitlist_entries_event_id_email"),
    )
    op.create_index(
        "ix_waitlist_entries_event_id_status", "waitlist_entries", ["event_id", "status"]
    )
    op.create_index("ix_waitlist_entries_created_at", "waitlist_entries", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_waitlist_entries_created_at", table_name="waitlist_entries")
    op.drop_index("ix_waitlist_entries_event_id_status", table_name="waitlist_entries")
    op.drop_table("waitlist_entries")
    postgresql.ENUM(name="waitlist_status").drop(op.get_bind(), checkfirst=True)
