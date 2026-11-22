"""Add promo_codes and the discount on bookings.

The booking total constraint changes from `subtotal + fees` to
`subtotal + fees - discount`, with the discount never above the subtotal, so a
discount can never produce a negative or inconsistent total.

Revision ID: d29a5b0c6e74
Revises: c18f4a9b5d63
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d29a5b0c6e74"
down_revision: str | None = "c18f4a9b5d63"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TYPES = ("PERCENT", "FIXED")


def upgrade() -> None:
    postgresql.ENUM(*TYPES, name="promo_discount_type").create(op.get_bind(), checkfirst=True)
    op.create_table(
        "promo_codes",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("code", sa.String(32), nullable=False, unique=True),
        sa.Column("description", sa.String(200)),
        sa.Column(
            "discount_type",
            postgresql.ENUM(*TYPES, name="promo_discount_type", create_type=False),
            nullable=False,
        ),
        sa.Column("percent_off", sa.Integer()),
        sa.Column("amount_off_paise", sa.BigInteger()),
        sa.Column(
            "event_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("events.id", ondelete="CASCADE"),
        ),
        sa.Column("max_uses", sa.Integer()),
        sa.Column("used_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_uses_per_customer", sa.Integer(), server_default="1"),
        sa.Column("valid_from", sa.DateTime(timezone=True)),
        sa.Column("valid_until", sa.DateTime(timezone=True)),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
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
            "(discount_type = 'PERCENT' AND percent_off BETWEEN 1 AND 100 "
            "AND amount_off_paise IS NULL) OR "
            "(discount_type = 'FIXED' AND amount_off_paise > 0 AND percent_off IS NULL)",
            name=op.f("ck_promo_codes_discount_matches_type"),
        ),
        sa.CheckConstraint("used_count >= 0", name=op.f("ck_promo_codes_used_count_not_negative")),
        sa.CheckConstraint(
            "max_uses IS NULL OR used_count <= max_uses",
            name=op.f("ck_promo_codes_used_within_max"),
        ),
        sa.CheckConstraint(
            "max_uses_per_customer IS NULL OR max_uses_per_customer >= 1",
            name=op.f("ck_promo_codes_per_customer_positive"),
        ),
        sa.CheckConstraint(
            "valid_until IS NULL OR valid_from IS NULL OR valid_until > valid_from",
            name=op.f("ck_promo_codes_window_ordered"),
        ),
    )
    op.create_index("ix_promo_codes_created_at", "promo_codes", ["created_at"])

    op.add_column(
        "bookings",
        sa.Column("discount_paise", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.add_column(
        "bookings",
        sa.Column(
            "promo_code_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("promo_codes.id", ondelete="SET NULL"),
        ),
    )
    op.drop_constraint(op.f("ck_bookings_total_is_subtotal_plus_fees"), "bookings", type_="check")
    op.create_check_constraint(
        op.f("ck_bookings_discount_not_negative"), "bookings", "discount_paise >= 0"
    )
    op.create_check_constraint(
        op.f("ck_bookings_discount_within_subtotal"),
        "bookings",
        "discount_paise <= subtotal_paise",
    )
    op.create_check_constraint(
        op.f("ck_bookings_total_is_subtotal_plus_fees_minus_discount"),
        "bookings",
        "total_paise = subtotal_paise + fees_paise - discount_paise",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_bookings_total_is_subtotal_plus_fees_minus_discount"), "bookings", type_="check"
    )
    op.drop_constraint(op.f("ck_bookings_discount_within_subtotal"), "bookings", type_="check")
    op.drop_constraint(op.f("ck_bookings_discount_not_negative"), "bookings", type_="check")
    op.create_check_constraint(
        op.f("ck_bookings_total_is_subtotal_plus_fees"),
        "bookings",
        "total_paise = subtotal_paise + fees_paise",
    )
    op.drop_column("bookings", "promo_code_id")
    op.drop_column("bookings", "discount_paise")
    op.drop_index("ix_promo_codes_created_at", table_name="promo_codes")
    op.drop_table("promo_codes")
    postgresql.ENUM(name="promo_discount_type").drop(op.get_bind(), checkfirst=True)
