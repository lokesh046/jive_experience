"""Add worker heartbeats and recurring-job runs.

Revision ID: d8a3b6c1e750
Revises: c7f2a5b8d649
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d8a3b6c1e750"
down_revision: str | None = "c7f2a5b8d649"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "worker_heartbeats",
        sa.Column("worker_id", sa.String(80), primary_key=True),
        sa.Column("host", sa.String(120), nullable=False),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_table(
        "job_runs",
        sa.Column("name", sa.String(60), primary_key=True),
        sa.Column("label", sa.String(120), nullable=False),
        sa.Column("interval_seconds", sa.Integer(), nullable=False),
        sa.Column("last_started_at", sa.DateTime(timezone=True)),
        sa.Column("last_finished_at", sa.DateTime(timezone=True)),
        sa.Column("last_status", sa.String(10)),
        sa.Column("last_error", sa.Text()),
        sa.Column("runs", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_table("job_runs")
    op.drop_table("worker_heartbeats")
