"""Give every queued job a priority, so urgent work never waits behind bulk work.

Revision ID: e9b4c7d2f861
Revises: d8a3b6c1e750
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e9b4c7d2f861"
down_revision: str | None = "d8a3b6c1e750"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "outbox_messages",
        sa.Column("priority", sa.SmallInteger(), nullable=False, server_default="1"),
    )
    # Existing rows get the priority their topic would have been given.
    op.execute(
        """
        UPDATE outbox_messages SET priority = CASE
            WHEN topic IN ('payment.captured', 'booking.confirmed', 'refund.process',
                           'event.cancelled') THEN 0
            WHEN topic = 'booking.reminder' THEN 2
            WHEN topic IN ('booking.abandoned', 'newsletter.send') THEN 3
            ELSE 1 END
        """
    )
    op.drop_index("ix_outbox_messages_claimable", table_name="outbox_messages")
    op.create_index(
        "ix_outbox_messages_claimable",
        "outbox_messages",
        ["priority", "available_at"],
        postgresql_where=sa.text("status IN ('PENDING', 'PROCESSING')"),
    )


def downgrade() -> None:
    op.drop_index("ix_outbox_messages_claimable", table_name="outbox_messages")
    op.create_index(
        "ix_outbox_messages_claimable",
        "outbox_messages",
        ["available_at"],
        postgresql_where=sa.text("status IN ('PENDING', 'PROCESSING')"),
    )
    op.drop_column("outbox_messages", "priority")
