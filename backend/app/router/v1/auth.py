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
from urllib.parse import urlencode

import structlog
from fastapi import APIRouter, BackgroundTasks, Query, status
from fastapi.responses import RedirectResponse

from app.core import mailer
from app.core.config import Environment
from app.core.errors import BusinessRuleError
from app.dependencies import (
    AppSettings,
    AuthServiceDep,
    CurrentUser,
    OAuthRateLimit,
    RefreshRateLimit,
    RequestContextDep,
)
from app.schemas.auth import (
    AuthenticatedUser,
    EmailCodeRequest,
    EmailCodeResponse,
    EmailCodeVerifyRequest,
    GoogleAuthorizationResponse,
    GoogleCallbackRequest,
    LogoutRequest,
    PhoneNumberRequest,
    RefreshRequest,
    TokenPair,
)

router = APIRouter(tags=["auth"])
logger = structlog.get_logger(__name__)


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
    app_redirect: Annotated[
        str | None,
        Query(description="The phone app's own link, to hand the sign-in back to", max_length=300),
    ] = None,
) -> GoogleAuthorizationResponse:
    """Return the URL to send the user to.

    The same endpoint serves customers, event staff and administrators. A
    one-time `state` and a PKCE challenge are generated here and held
    server-side, so the callback cannot be forged or replayed.
    """
    request = await service.start_google_sign_in(redirect_uri, app_redirect)
    return GoogleAuthorizationResponse(
        authorization_url=request.authorization_url, state=request.state
    )


@router.get("/google/mobile-return", include_in_schema=False)
async def google_mobile_return(
    service: AuthServiceDep,
    code: Annotated[str | None, Query(max_length=2000)] = None,
    state: Annotated[str | None, Query(max_length=200)] = None,
    error: Annotated[str | None, Query(max_length=200)] = None,
) -> RedirectResponse:
    """Where Google sends the person back for the phone app: on to the app's own link.

    Nothing is signed in here. The app takes the code and state and finishes through
    `POST /google/callback`, exactly as the website does.
    """
    target = await service.app_return_url(state) if state else None
    if target is None:
        raise BusinessRuleError(
            "This sign-in link has expired. Please try again.", code="OAUTH_STATE_INVALID"
        )
    query = urlencode(
        {k: v for k, v in {"code": code, "state": state, "error": error}.items() if v}
    )
    return RedirectResponse(f"{target}{'&' if '?' in target else '?'}{query}", status_code=302)


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


# ------------------------------------------------------- email code sign-in ---


@router.post(
    "/email/request",
    response_model=EmailCodeResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Email a one-time sign-in code",
    dependencies=[OAuthRateLimit],
)
async def email_code_request(
    payload: EmailCodeRequest,
    service: AuthServiceDep,
    settings: AppSettings,
    background: BackgroundTasks,
) -> EmailCodeResponse:
    """Always answers the same way, so it cannot be used to find out who has an account."""
    code = await service.request_email_code(str(payload.email))
    if code is not None:
        if settings.email_configured:
            background.add_task(_send_code, settings, str(payload.email).strip().lower(), code)
        elif settings.environment in (Environment.LOCAL, Environment.TEST):
            logger.warning("email_code_not_sent_no_smtp", email=str(payload.email), code=code)
    return EmailCodeResponse(message="If that address can sign in, a code is on its way.")


async def _send_code(settings: AppSettings, to: str, code: str) -> None:
    try:
        await mailer.send_mail(settings, mailer.login_code_mail(to=to, code=code, minutes=10))
    except Exception:  # the person just asks for another code
        logger.exception("login_code_email_failed")


@router.post(
    "/email/verify",
    response_model=TokenPair,
    summary="Sign in with the emailed code",
    dependencies=[OAuthRateLimit],
)
async def email_code_verify(
    payload: EmailCodeVerifyRequest,
    service: AuthServiceDep,
    context: RequestContextDep,
) -> TokenPair:
    issued = await service.verify_email_code(str(payload.email), payload.code, context=context)
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
