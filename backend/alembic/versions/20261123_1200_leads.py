"""Add enquiries and newsletter_subscribers.

Revision ID: b07e3f8a4c52
Revises: a96d2e7f3b41
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b07e3f8a4c52"
down_revision: str | None = "a96d2e7f3b41"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATUSES = ("NEW", "CONTACTED", "CLOSED")


def _id() -> sa.Column:  # type: ignore[type-arg]
    return sa.Column(
        "id",
        postgresql.UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )


def _stamps() -> list[sa.Column]:  # type: ignore[type-arg]
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    ]


def upgrade() -> None:
    postgresql.ENUM(*STATUSES, name="enquiry_status").create(op.get_bind(), checkfirst=True)
    op.create_table(
        "enquiries",
        _id(),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("phone", sa.String(30)),
        sa.Column("event_date", sa.Date()),
        sa.Column("guests", sa.Integer()),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(*STATUSES, name="enquiry_status", create_type=False),
            nullable=False,
            server_default="NEW",
        ),
        sa.Column("admin_note", sa.Text()),
        sa.Column(
            "handled_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        *_stamps(),
    )
    op.create_index("ix_enquiries_status_created_at", "enquiries", ["status", "created_at"])
    op.create_index("ix_enquiries_created_at", "enquiries", ["created_at"])

    op.create_table(
        "newsletter_subscribers",
        _id(),
        sa.Column("email", sa.String(320), nullable=False, unique=True),
        sa.Column("subscribed", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("unsubscribe_token", sa.String(64), nullable=False, unique=True),
        sa.Column("unsubscribed_at", sa.DateTime(timezone=True)),
        *_stamps(),
    )
    op.create_index(
        "ix_newsletter_subscribers_created_at", "newsletter_subscribers", ["created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_newsletter_subscribers_created_at", table_name="newsletter_subscribers")
    op.drop_table("newsletter_subscribers")
    op.drop_index("ix_enquiries_created_at", table_name="enquiries")
    op.drop_index("ix_enquiries_status_created_at", table_name="enquiries")
    op.drop_table("enquiries")
    postgresql.ENUM(name="enquiry_status").drop(op.get_bind(), checkfirst=True)
