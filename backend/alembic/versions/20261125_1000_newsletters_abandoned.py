"""Add newsletter campaigns and the abandoned-booking marker.

Revision ID: a5d9e3f1b427
Revises: f4c8d2e9a316
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a5d9e3f1b427"
down_revision: str | None = "f4c8d2e9a316"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "newsletter_campaigns",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("subject", sa.String(200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "event_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("events.id", ondelete="SET NULL"),
        ),
        sa.Column("button_label", sa.String(60)),
        sa.Column("button_url", sa.String(500)),
        sa.Column("status", sa.String(12), nullable=False, server_default="DRAFT"),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("recipients", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("delivered", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'SENT')", name=op.f("ck_newsletter_campaigns_status_known")
        ),
        sa.CheckConstraint(
            "char_length(btrim(subject)) > 0",
            name=op.f("ck_newsletter_campaigns_subject_not_blank"),
        ),
        sa.CheckConstraint(
            "char_length(btrim(body)) > 0", name=op.f("ck_newsletter_campaigns_body_not_blank")
        ),
    )
    op.create_index("ix_newsletter_campaigns_created_at", "newsletter_campaigns", ["created_at"])
    op.add_column(
        "bookings", sa.Column("abandoned_notified_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("bookings", "abandoned_notified_at")
    op.drop_index("ix_newsletter_campaigns_created_at", table_name="newsletter_campaigns")
    op.drop_table("newsletter_campaigns")
