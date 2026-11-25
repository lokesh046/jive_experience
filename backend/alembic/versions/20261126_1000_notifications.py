"""Add notifications and notification preferences.

Revision ID: b6e1f4a9c538
Revises: a5d9e3f1b427
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b6e1f4a9c538"
down_revision: str | None = "a5d9e3f1b427"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "notifications",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(60), nullable=False),
        sa.Column("category", sa.String(30), nullable=False),
        sa.Column("severity", sa.String(10), nullable=False, server_default="info"),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("body", sa.String(500)),
        sa.Column("link", sa.String(300)),
        sa.Column("dedup_key", sa.String(160)),
        sa.Column("data", postgresql.JSONB()),
        sa.Column("read_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "severity IN ('info', 'warn', 'critical')",
            name=op.f("ck_notifications_severity_known"),
        ),
        sa.CheckConstraint(
            "link IS NULL OR link LIKE '/%'", name=op.f("ck_notifications_link_is_a_path")
        ),
    )
    op.create_index(
        "ix_notifications_user_id_created_at", "notifications", ["user_id", "created_at"]
    )
    op.create_index(
        "uq_notifications_user_id_dedup_key",
        "notifications",
        ["user_id", "dedup_key"],
        unique=True,
        postgresql_where=sa.text("dedup_key IS NOT NULL"),
    )
    op.create_index(
        "ix_notifications_unread",
        "notifications",
        ["user_id"],
        postgresql_where=sa.text("read_at IS NULL"),
    )
    op.create_index("ix_notifications_created_at", "notifications", ["created_at"])
    op.create_table(
        "notification_preferences",
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("category", sa.String(30), primary_key=True),
        sa.Column("channel", sa.String(10), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.CheckConstraint(
            "channel IN ('in_app', 'email')",
            name=op.f("ck_notification_preferences_channel_known"),
        ),
    )


def downgrade() -> None:
    op.drop_table("notification_preferences")
    op.drop_index("ix_notifications_created_at", table_name="notifications")
    op.drop_index("ix_notifications_unread", table_name="notifications")
    op.drop_index("uq_notifications_user_id_dedup_key", table_name="notifications")
    op.drop_index("ix_notifications_user_id_created_at", table_name="notifications")
    op.drop_table("notifications")
