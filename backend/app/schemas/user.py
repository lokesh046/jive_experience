"""User request and response contracts.

Two output shapes on purpose: a customer sees `UserProfile` (their own data),
an administrator sees `UserAdminView` (operational fields). Returning the admin
shape to a customer would leak account state and timestamps.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.models.user import UserRole, UserStatus


class UserProfile(BaseModel):
    """What a signed-in user sees about themselves."""

    id: uuid.UUID
    role: UserRole
    email: str
    full_name: str | None = None
    phone_e164: str | None = None
    avatar_url: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class UserProfileUpdate(BaseModel):
    """Fields a user may change about themselves.

    Not here, deliberately: role, status, email and phone. The email is the
    identity Google asserts, and the phone has its own verified endpoint.
    """

    full_name: Annotated[str | None, Field(default=None, min_length=1, max_length=120)] = None

    @field_validator("full_name")
    @classmethod
    def _strip(cls, value: str | None) -> str | None:
        return value.strip() if value else value


class UserAdminView(BaseModel):
    """What an administrator sees about any account."""

    id: uuid.UUID
    role: UserRole
    status: UserStatus
    email: str
    full_name: str | None = None
    phone_e164: str | None = None
    last_login_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class StaffCreateRequest(BaseModel):
    """Grant an email address administrator or event-staff access.

    No password: the person signs in with Google. Creating this row is what
    authorises that Google account — the next time they sign in, the verified
    email matches and they get this role.

    The address must be the one on their Google account, and that account must
    have two-factor authentication enabled, because it is now the only thing
    standing between an attacker and the dashboard.
    """

    email: EmailStr
    full_name: Annotated[str, Field(min_length=1, max_length=120)]
    role: UserRole = UserRole.EVENT_STAFF

    @field_validator("role")
    @classmethod
    def _privileged_only(cls, value: UserRole) -> UserRole:
        if value is UserRole.CUSTOMER:
            raise ValueError("Customer accounts are created automatically on first sign-in.")
        return value


class UserStatusUpdate(BaseModel):
    status: UserStatus
    reason: Annotated[str | None, Field(default=None, max_length=280)] = None
