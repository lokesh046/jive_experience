"""User accounts.

One table holds all three roles. They are genuinely the same entity — a person
with an identity and a set of permissions — and splitting them would duplicate
every foreign key that points at "whoever did this".

**Everyone signs in with Google OAuth 2.0.** There are no passwords anywhere
in this system: customers, event staff and administrators all authenticate the
same way, and the email address Google verifies is the identity.

Authorisation is therefore a property of the *row*, not of the credential. A
privileged account exists because an administrator (or the bootstrap CLI)
created a row with that email and that role **before** the person ever signed
in. Google sign-in only proves who someone is; it never grants a role, and
there is no code path by which signing in can elevate one.

That makes the account's Google security the system's security: every admin
and staff Gmail account must have two-factor authentication enabled. See
`docs/google-oauth-setup.md`.

`phone_e164` is optional at sign-up. Google accounts are free and unlimited, so
a verified phone number is the control that makes per-account purchase limits
mean anything; Phase 4 requires one before a reservation can be made. See
`docs/anti-bot.md`.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, DateTime, Enum, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class UserRole(StrEnum):
    ADMIN = "ADMIN"
    CUSTOMER = "CUSTOMER"
    EVENT_STAFF = "EVENT_STAFF"


class UserStatus(StrEnum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DEACTIVATED = "DEACTIVATED"


user_role_enum = Enum(
    UserRole,
    name="user_role",
    values_callable=lambda enum: [member.value for member in enum],
)
user_status_enum = Enum(
    UserStatus,
    name="user_status",
    values_callable=lambda enum: [member.value for member in enum],
)


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"

    role: Mapped[UserRole] = mapped_column(user_role_enum, nullable=False, index=True)
    status: Mapped[UserStatus] = mapped_column(
        user_status_enum, nullable=False, default=UserStatus.ACTIVE
    )

    # Shared identity for both sign-in paths.
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    full_name: Mapped[str | None] = mapped_column(String(120))

    # E.164, e.g. "+919876543210". Optional at sign-up, verified before a
    # customer may reserve tickets.
    phone_e164: Mapped[str | None] = mapped_column(String(16), unique=True)

    # Google's stable subject identifier. Never the email: a Google account's
    # email address can change, the subject cannot.
    google_sub: Mapped[str | None] = mapped_column(String(255), unique=True)
    avatar_url: Mapped[str | None] = mapped_column(String(512))

    # Access tokens issued before this instant are refused. Set by
    # "sign out everywhere", by suspension, and by a role change.
    #
    # This is what makes revocation immediate without costing a query: the
    # user row is already loaded to check `status`, so the comparison is free.
    # The alternative — looking the session up in `refresh_tokens` on every
    # request — would add a round trip to every authenticated call, which
    # during a ticket release is the one thing that cannot be afforded.
    sessions_valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    phone_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "phone_e164 IS NULL OR phone_e164 ~ '^\\+[1-9][0-9]{7,14}$'",
            name="phone_is_e164",
        ),
        Index("ix_users_role_status", "role", "status"),
    )

    @property
    def is_active(self) -> bool:
        return self.status is UserStatus.ACTIVE

    @property
    def is_privileged(self) -> bool:
        return self.role in (UserRole.ADMIN, UserRole.EVENT_STAFF)

    @property
    def has_signed_in(self) -> bool:
        """Whether this account has ever completed Google sign-in.

        A pre-provisioned admin or staff row has no `google_sub` until the
        person signs in for the first time; the email match is what links
        them.
        """
        return self.google_sub is not None
