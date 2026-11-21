"""Initial schema: identity, sessions and the audit trail.

Creates the foundation every later phase hangs off:

* `users`          — one table for ADMIN / CUSTOMER / EVENT_STAFF, with CHECK
                     constraints that make a privileged account impossible to
                     create through the customer OTP path.
* `refresh_tokens` — hashed, rotating refresh tokens with a family id so a
                     stolen token can be detected and its whole chain revoked.
* `audit_logs`     — append-only record of sensitive administrative actions.

Notes
-----
`gen_random_uuid()` is built into PostgreSQL 13+; no extension is required.

The PostgreSQL ENUM types are created explicitly before the tables rather than
implicitly by the first column that uses them: `user_role` is referenced by both
`users` and `audit_logs`, and the implicit path would emit CREATE TYPE twice
and fail. Creating them here also lets `downgrade()` drop them, so that
downgrade followed by upgrade works — which is exactly the path a failed
production deploy takes.

Revision ID: 274b3ece4c19
Revises:
Create Date: 2026-11-20 07:48:40.138791+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "274b3ece4c19"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# create_type=False: the types are created once, by hand, in upgrade().
user_role = postgresql.ENUM("ADMIN", "CUSTOMER", "EVENT_STAFF", name="user_role", create_type=False)
user_status = postgresql.ENUM(
    "ACTIVE", "SUSPENDED", "DEACTIVATED", name="user_status", create_type=False
)
token_revocation_reason = postgresql.ENUM(
    "LOGOUT",
    "ROTATED",
    "REUSE_DETECTED",
    "ADMIN_REVOKED",
    "PASSWORD_CHANGED",
    "ACCOUNT_SUSPENDED",
    name="token_revocation_reason",
    create_type=False,
)

ENUM_TYPES = (user_role, user_status, token_revocation_reason)


def upgrade() -> None:
    bind = op.get_bind()
    for enum_type in ENUM_TYPES:
        enum_type.create(bind, checkfirst=True)

    # ----------------------------------------------------------- users ----
    op.create_table(
        "users",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("role", user_role, nullable=False),
        sa.Column("status", user_status, nullable=False),
        sa.Column("phone_e164", sa.String(length=16), nullable=True),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("full_name", sa.String(length=120), nullable=True),
        sa.Column("firebase_uid", sa.String(length=128), nullable=True),
        sa.Column("password_hash", sa.String(length=255), nullable=True),
        sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("phone_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(role <> 'CUSTOMER') OR (phone_e164 IS NOT NULL AND password_hash IS NULL)",
            name=op.f("ck_users_customer_has_phone_and_no_password"),
        ),
        sa.CheckConstraint(
            "(role = 'CUSTOMER') OR (email IS NOT NULL AND password_hash IS NOT NULL)",
            name=op.f("ck_users_privileged_has_email_and_password"),
        ),
        sa.CheckConstraint(
            "phone_e164 IS NULL OR phone_e164 ~ '^\\+[1-9][0-9]{7,14}$'",
            name=op.f("ck_users_phone_is_e164"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
        sa.UniqueConstraint("firebase_uid", name=op.f("uq_users_firebase_uid")),
        sa.UniqueConstraint("phone_e164", name=op.f("uq_users_phone_e164")),
    )
    op.create_index(op.f("ix_users_created_at"), "users", ["created_at"])
    op.create_index(op.f("ix_users_role"), "users", ["role"])
    op.create_index("ix_users_role_status", "users", ["role", "status"])

    # -------------------------------------------------- refresh_tokens ----
    op.create_table(
        "refresh_tokens",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("family_id", sa.UUID(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revocation_reason", token_revocation_reason, nullable=True),
        sa.Column("replaced_by_id", sa.UUID(), nullable=True),
        sa.Column("user_agent", sa.String(length=400), nullable=True),
        sa.Column("ip_address", postgresql.INET(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["replaced_by_id"],
            ["refresh_tokens.id"],
            name=op.f("fk_refresh_tokens_replaced_by_id_refresh_tokens"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_refresh_tokens_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_refresh_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_refresh_tokens_token_hash")),
    )
    op.create_index(op.f("ix_refresh_tokens_created_at"), "refresh_tokens", ["created_at"])
    op.create_index("ix_refresh_tokens_expires_at", "refresh_tokens", ["expires_at"])
    op.create_index(op.f("ix_refresh_tokens_family_id"), "refresh_tokens", ["family_id"])
    op.create_index(op.f("ix_refresh_tokens_user_id"), "refresh_tokens", ["user_id"])
    op.create_index(
        "ix_refresh_tokens_user_id_revoked_at", "refresh_tokens", ["user_id", "revoked_at"]
    )

    # ------------------------------------------------------ audit_logs ----
    op.create_table(
        "audit_logs",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("actor_user_id", sa.UUID(), nullable=True),
        sa.Column("actor_role", user_role, nullable=True),
        sa.Column("actor_label", sa.String(length=160), nullable=True),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("entity_type", sa.String(length=60), nullable=False),
        sa.Column("entity_id", sa.String(length=64), nullable=True),
        sa.Column("before", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("after", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("context", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column("ip_address", postgresql.INET(), nullable=True),
        sa.Column("user_agent", sa.String(length=400), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name=op.f("fk_audit_logs_actor_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_logs")),
    )
    op.create_index(op.f("ix_audit_logs_action"), "audit_logs", ["action"])
    op.create_index("ix_audit_logs_action_created_at", "audit_logs", ["action", "created_at"])
    op.create_index(op.f("ix_audit_logs_actor_user_id"), "audit_logs", ["actor_user_id"])
    op.create_index(op.f("ix_audit_logs_created_at"), "audit_logs", ["created_at"])
    op.create_index("ix_audit_logs_entity", "audit_logs", ["entity_type", "entity_id"])
    op.create_index(op.f("ix_audit_logs_request_id"), "audit_logs", ["request_id"])


def downgrade() -> None:
    op.drop_table("audit_logs")
    op.drop_table("refresh_tokens")
    op.drop_table("users")

    bind = op.get_bind()
    for enum_type in ENUM_TYPES:
        enum_type.drop(bind, checkfirst=True)
