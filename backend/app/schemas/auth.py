"""Authentication request and response contracts."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Annotated, Literal

from pydantic import BaseModel, Field

from app.models.user import UserRole

if TYPE_CHECKING:  # pragma: no cover
    from app.services.auth import IssuedTokens


class GoogleAuthorizationResponse(BaseModel):
    """Where to send the user to sign in with Google."""

    authorization_url: str
    state: str = Field(description="Echo this back on the callback")


class GoogleCallbackRequest(BaseModel):
    """The authorization code Google redirected back with."""

    code: Annotated[str, Field(min_length=10, max_length=2048)]
    state: Annotated[str, Field(min_length=10, max_length=256)]


class PhoneNumberRequest(BaseModel):
    """Attach a phone number to the signed-in account.

    Required before booking: a Google account is free and unlimited, so the
    phone number is what makes a per-account purchase limit meaningful.
    """

    phone_e164: Annotated[
        str,
        Field(
            min_length=8,
            max_length=16,
            pattern=r"^\+[1-9][0-9]{7,14}$",
            description="E.164 format, e.g. +919876543210",
        ),
    ]


class RefreshRequest(BaseModel):
    refresh_token: Annotated[str, Field(min_length=20, max_length=512)]


class LogoutRequest(BaseModel):
    refresh_token: Annotated[str, Field(min_length=20, max_length=512)]


class AuthenticatedUser(BaseModel):
    """The caller's own identity, returned alongside a token pair."""

    id: uuid.UUID
    role: UserRole
    email: str
    full_name: str | None = None
    phone_e164: str | None = None
    avatar_url: str | None = None

    model_config = {"from_attributes": True}


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int = Field(description="Access token lifetime in seconds")
    user: AuthenticatedUser

    @classmethod
    def from_issued(cls, issued: IssuedTokens) -> TokenPair:
        """Build the response from what the auth service returned.

        Imported only for type checking, so the schema layer carries no
        runtime dependency on the service layer.
        """
        return cls(
            access_token=issued.access_token,
            refresh_token=issued.refresh_token,
            expires_in=issued.expires_in,
            user=AuthenticatedUser.model_validate(issued.user),
        )
