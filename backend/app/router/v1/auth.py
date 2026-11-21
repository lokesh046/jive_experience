"""Authentication endpoints.

**One sign-in path for everyone.** Customers, event staff and administrators
all use the same Google OAuth 2.0 flow; there is no password login anywhere.

What differs is the account, not the route: an administrator's row was created
with that role before they ever signed in, and the verified Google email is
what links them to it. Signing in cannot grant a role.

Rate limited fail-closed; the limits live in `app/dependencies.py`.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, status

from app.dependencies import (
    AuthServiceDep,
    CurrentUser,
    OAuthRateLimit,
    RefreshRateLimit,
    RequestContextDep,
)
from app.schemas.auth import (
    AuthenticatedUser,
    GoogleAuthorizationResponse,
    GoogleCallbackRequest,
    LogoutRequest,
    PhoneNumberRequest,
    RefreshRequest,
    TokenPair,
)

router = APIRouter(tags=["auth"])


# ----------------------------------------------------------- Google sign-in ---


@router.get(
    "/google/authorize",
    response_model=GoogleAuthorizationResponse,
    summary="Begin Google sign-in",
    dependencies=[OAuthRateLimit],
)
async def google_authorize(
    service: AuthServiceDep,
    redirect_uri: Annotated[
        str | None,
        Query(description="Overrides the configured redirect URI; must be registered"),
    ] = None,
) -> GoogleAuthorizationResponse:
    """Return the URL to send the user to.

    The same endpoint serves customers, event staff and administrators. A
    one-time `state` and a PKCE challenge are generated here and held
    server-side, so the callback cannot be forged or replayed.
    """
    request = await service.start_google_sign_in(redirect_uri)
    return GoogleAuthorizationResponse(
        authorization_url=request.authorization_url, state=request.state
    )


@router.post(
    "/google/callback",
    response_model=TokenPair,
    summary="Complete Google sign-in",
    dependencies=[OAuthRateLimit],
)
async def google_callback(
    payload: GoogleCallbackRequest,
    service: AuthServiceDep,
    context: RequestContextDep,
) -> TokenPair:
    """Exchange the authorization code for application tokens.

    If the verified email matches an existing account — including one an
    administrator pre-created with a staff or admin role — that account is
    signed in with the role it already has. Otherwise a CUSTOMER account is
    created. This path can never produce a privileged account by itself.
    """
    issued = await service.complete_google_sign_in(
        code=payload.code, state=payload.state, context=context
    )
    return TokenPair.from_issued(issued)


@router.put(
    "/phone",
    response_model=AuthenticatedUser,
    summary="Set the signed-in account's phone number",
)
async def set_phone_number(
    payload: PhoneNumberRequest,
    user: CurrentUser,
    service: AuthServiceDep,
) -> AuthenticatedUser:
    """Required before booking — see `docs/anti-bot.md`."""
    updated = await service.set_phone_number(user, payload.phone_e164)
    return AuthenticatedUser.model_validate(updated)


# --------------------------------------------------------- session handling ---


@router.post(
    "/refresh",
    response_model=TokenPair,
    summary="Rotate a refresh token",
    dependencies=[RefreshRateLimit],
)
async def refresh(
    payload: RefreshRequest,
    service: AuthServiceDep,
    context: RequestContextDep,
) -> TokenPair:
    """Exchange a refresh token for a new pair.

    Rotation: the presented token is invalidated. Presenting an already-rotated
    token revokes the whole session family — that only happens if it leaked.
    """
    issued = await service.refresh(payload.refresh_token, context=context)
    return TokenPair.from_issued(issued)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="End this session")
async def logout(payload: LogoutRequest, service: AuthServiceDep) -> None:
    await service.logout(payload.refresh_token)


@router.post(
    "/logout-all",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="End every session for the signed-in account",
)
async def logout_all(user: CurrentUser, service: AuthServiceDep) -> None:
    await service.logout_everywhere(user)


@router.get("/me", response_model=AuthenticatedUser, summary="The signed-in account")
async def me(user: CurrentUser) -> AuthenticatedUser:
    return AuthenticatedUser.model_validate(user)
