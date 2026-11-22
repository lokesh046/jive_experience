"""Add events.location_url: a map link for the event.

Revision ID: d52f8b3e7a14
Revises: c41e7a9d2b60
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d52f8b3e7a14"
down_revision: str | None = "c41e7a9d2b60"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("events", sa.Column("location_url", sa.String(1024)))


def downgrade() -> None:
    op.drop_column("events", "location_url")
