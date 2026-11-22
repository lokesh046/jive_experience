"""Add bookings.source and issued_by_id for complimentary and cash tickets.

Revision ID: a96d2e7f3b41
Revises: f85c1d6e2a39
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a96d2e7f3b41"
down_revision: str | None = "f85c1d6e2a39"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SOURCES = ("ONLINE", "COMPLIMENTARY", "CASH")


def upgrade() -> None:
    source = postgresql.ENUM(*SOURCES, name="booking_source")
    source.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "bookings",
        sa.Column(
            "source",
            postgresql.ENUM(*SOURCES, name="booking_source", create_type=False),
            nullable=False,
            server_default="ONLINE",
        ),
    )
    op.add_column(
        "bookings",
        sa.Column(
            "issued_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
    )


def downgrade() -> None:
    op.drop_column("bookings", "issued_by_id")
    op.drop_column("bookings", "source")
    postgresql.ENUM(name="booking_source").drop(op.get_bind(), checkfirst=True)
