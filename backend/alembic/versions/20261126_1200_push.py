"""Add browser push subscriptions and a push channel for notification preferences.

Revision ID: c7f2a5b8d649
Revises: b6e1f4a9c538
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c7f2a5b8d649"
down_revision: str | None = "b6e1f4a9c538"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "push_subscriptions",
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
        sa.Column("endpoint", sa.String(1024), nullable=False, unique=True),
        sa.Column("p256dh", sa.String(200), nullable=False),
        sa.Column("auth", sa.String(100), nullable=False),
        sa.Column("user_agent", sa.String(300)),
        sa.Column("last_sent_at", sa.DateTime(timezone=True)),
        sa.Column("failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_push_subscriptions_user_id", "push_subscriptions", ["user_id"])
    op.create_index("ix_push_subscriptions_created_at", "push_subscriptions", ["created_at"])
    op.drop_constraint(
        op.f("ck_notification_preferences_channel_known"),
        "notification_preferences",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_notification_preferences_channel_known"),
        "notification_preferences",
        "channel IN ('in_app', 'email', 'push')",
    )


def downgrade() -> None:
    op.execute("DELETE FROM notification_preferences WHERE channel = 'push'")
    op.drop_constraint(
        op.f("ck_notification_preferences_channel_known"),
        "notification_preferences",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_notification_preferences_channel_known"),
        "notification_preferences",
        "channel IN ('in_app', 'email')",
    )
    op.drop_index("ix_push_subscriptions_created_at", table_name="push_subscriptions")
    op.drop_index("ix_push_subscriptions_user_id", table_name="push_subscriptions")
    op.drop_table("push_subscriptions")
