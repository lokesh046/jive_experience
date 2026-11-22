"""Add venue description, photos and benefits.

Revision ID: e63a9c4d1f28
Revises: d52f8b3e7a14
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e63a9c4d1f28"
down_revision: str | None = "d52f8b3e7a14"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("venues", sa.Column("description", sa.Text()))
    op.add_column("venues", sa.Column("image_urls", postgresql.JSONB()))
    op.add_column("venues", sa.Column("benefits", postgresql.JSONB()))


def downgrade() -> None:
    op.drop_column("venues", "benefits")
    op.drop_column("venues", "image_urls")
    op.drop_column("venues", "description")
