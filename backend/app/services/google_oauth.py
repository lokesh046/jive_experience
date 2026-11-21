"""Google OAuth 2.0 (OpenID Connect) sign-in.

Authorization Code flow with PKCE:

1. The client asks us for an authorization URL. We mint a `state` and a PKCE
   `code_verifier`, keep both in Redis, and return the URL.
2. The user signs in at Google and is redirected back with a `code`.
3. The client posts the `code` and `state` here. We check the state, exchange
   the code (sending the stored verifier), verify the returned ID token
   against Google's public keys, and hand back the verified identity.

Why this shape rather than accepting an ID token straight from the browser:

* `state` ties the callback to the request we issued, which is what stops
  login CSRF — an attacker cannot make a victim's browser complete *their*
  sign-in.
* PKCE binds the code to this client, so an intercepted code is useless.
* The client secret stays on the server and never reaches the frontend.

The same endpoints work for a web app and for future mobile clients.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt
import structlog

from app.core.config import Settings
from app.core.errors import AuthenticationError, ServiceUnavailableError

logger = structlog.get_logger(__name__)

AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
JWKS_URI = "https://www.googleapis.com/oauth2/v3/certs"
VALID_ISSUERS = frozenset({"accounts.google.com", "https://accounts.google.com"})

SCOPES = ("openid", "email", "profile")
JWKS_CACHE_SECONDS = 3600
HTTP_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


@dataclass(frozen=True, slots=True)
class GoogleIdentity:
    """The verified claims we use from a Google ID token."""

    subject: str
    email: str
    email_verified: bool
    full_name: str | None
    picture: str | None


@dataclass(frozen=True, slots=True)
class AuthorizationRequest:
    """What the client needs to start the flow."""

    authorization_url: str
    state: str


def generate_pkce_pair() -> tuple[str, str]:
    """Return (code_verifier, code_challenge) for the S256 method."""
    verifier = secrets.token_urlsafe(64)[:128]
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


class _JwksCache:
    """Google's signing keys, cached in-process.

    Google rotates these keys; fetching them on every sign-in would add a
    round trip to Google on the critical path and would fall over if Google
    rate-limited us during a ticket drop.
    """

    def __init__(self) -> None:
        self._keys: dict[str, Any] | None = None
        self._fetched_at = 0.0

    async def get(self, *, force: bool = False) -> dict[str, Any]:
        fresh = time.monotonic() - self._fetched_at < JWKS_CACHE_SECONDS
        if self._keys is not None and fresh and not force:
            return self._keys

        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
                response = await client.get(JWKS_URI)
                response.raise_for_status()
                self._keys = response.json()
        except httpx.HTTPError as exc:
            logger.error("google_jwks_fetch_failed", error=str(exc))
            if self._keys is not None:
                # Serve the stale copy rather than refusing every sign-in
                # because Google was briefly unreachable.
                return self._keys
            raise ServiceUnavailableError(
                "Could not reach Google to verify the sign-in. Please try again.",
                code="GOOGLE_UNAVAILABLE",
            ) from exc

        self._fetched_at = time.monotonic()
        assert self._keys is not None
        return self._keys


class GoogleOAuthClient:
    """Talks to Google. Knows nothing about our users or tokens."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._jwks = _JwksCache()

    @property
    def configured(self) -> bool:
        return self.settings.google_oauth_configured

    def _require_configured(self) -> tuple[str, str]:
        if not self.settings.google_client_id or not self.settings.google_client_secret:
            raise ServiceUnavailableError(
                "Google sign-in is not configured on this server.",
                code="GOOGLE_NOT_CONFIGURED",
            )
        return (
            self.settings.google_client_id,
            self.settings.google_client_secret.get_secret_value(),
        )

    def build_authorization_url(self, *, state: str, code_challenge: str, redirect_uri: str) -> str:
        client_id, _ = self._require_configured()
        params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(SCOPES),
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            # Ask Google to show the account chooser rather than silently
            # reusing whichever account the browser is already signed into.
            "prompt": "select_account",
        }
        return f"{AUTHORIZATION_ENDPOINT}?{urlencode(params)}"

    async def exchange_code(self, *, code: str, code_verifier: str, redirect_uri: str) -> str:
        """Swap an authorization code for Google's ID token."""
        client_id, client_secret = self._require_configured()
        payload = {
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
            "code_verifier": code_verifier,
        }

        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
                response = await client.post(TOKEN_ENDPOINT, data=payload)
        except httpx.HTTPError as exc:
            logger.error("google_token_exchange_failed", error=str(exc))
            raise ServiceUnavailableError(
                "Could not reach Google to complete sign-in. Please try again.",
                code="GOOGLE_UNAVAILABLE",
            ) from exc

        if response.status_code != httpx.codes.OK:
            # Google reports a bad/expired/replayed code here. The body can
            # contain the client secret echo, so only the error code is logged.
            detail = response.json().get("error") if response.content else None
            logger.info("google_code_rejected", google_error=detail)
            raise AuthenticationError(
                "Google sign-in could not be completed. Please try again.",
                code="GOOGLE_CODE_INVALID",
            )

        id_token = response.json().get("id_token")
        if not id_token:
            raise AuthenticationError(
                "Google did not return an identity token.", code="GOOGLE_NO_ID_TOKEN"
            )
        return str(id_token)

    async def verify_id_token(self, id_token: str) -> GoogleIdentity:
        """Verify the ID token's signature, issuer, audience and expiry."""
        client_id, _ = self._require_configured()

        try:
            header = jwt.get_unverified_header(id_token)
        except jwt.InvalidTokenError as exc:
            raise AuthenticationError(
                "Invalid Google identity token.", code="GOOGLE_TOKEN_INVALID"
            ) from exc

        key = await self._signing_key(header.get("kid"))

        try:
            claims = jwt.decode(
                id_token,
                key=key,
                algorithms=["RS256"],
                audience=client_id,
                options={"require": ["exp", "iat", "sub", "aud", "iss"]},
            )
        except jwt.ExpiredSignatureError as exc:
            raise AuthenticationError(
                "The Google sign-in has expired. Please try again.",
                code="GOOGLE_TOKEN_EXPIRED",
            ) from exc
        except jwt.InvalidTokenError as exc:
            raise AuthenticationError(
                "Invalid Google identity token.", code="GOOGLE_TOKEN_INVALID"
            ) from exc

        if claims.get("iss") not in VALID_ISSUERS:
            raise AuthenticationError("Invalid Google identity token.", code="GOOGLE_TOKEN_INVALID")

        email = claims.get("email")
        if not email:
            raise AuthenticationError(
                "Your Google account did not share an email address.",
                code="GOOGLE_EMAIL_REQUIRED",
            )

        return GoogleIdentity(
            subject=str(claims["sub"]),
            email=str(email).lower(),
            email_verified=bool(claims.get("email_verified", False)),
            full_name=claims.get("name"),
            picture=claims.get("picture"),
        )

    async def _signing_key(self, kid: str | None) -> Any:
        """Find Google's public key for this token, refreshing on a miss.

        A miss is expected whenever Google rotates its keys, so one forced
        refresh is attempted before giving up.
        """
        for force in (False, True):
            jwks = await self._jwks.get(force=force)
            for entry in jwks.get("keys", []):
                if entry.get("kid") == kid:
                    return jwt.PyJWK(entry).key
        raise AuthenticationError("Invalid Google identity token.", code="GOOGLE_TOKEN_INVALID")
