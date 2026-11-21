"""Application token handling.

There is no password hashing here, deliberately: every account — customer,
event staff and administrator — signs in with Google OAuth 2.0, so this system
never holds a password to hash. Removing that path removes credential
stuffing, password reset and password storage from the threat model entirely.

Two kinds of token, deliberately different:

* **Access token** — a short-lived signed JWT. Stateless, so it is never read
  from the database on a request; that is what keeps authorisation cheap at
  checkout under load. The cost is that it cannot be revoked before it
  expires, which is why it is short-lived.
* **Refresh token** — a long, opaque random string. It is *not* a JWT: it is
  looked up in the database on every use, so it can be revoked instantly. Only
  a SHA-256 digest is stored, so a database disclosure yields no usable
  sessions.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import jwt

from app.core.config import Settings
from app.core.errors import AuthenticationError

ALGORITHM = "HS256"
REFRESH_TOKEN_BYTES = 48


# ------------------------------------------------------------ access tokens ---


@dataclass(frozen=True, slots=True)
class AccessTokenClaims:
    """The verified contents of an access token."""

    user_id: uuid.UUID
    role: str
    token_id: str
    issued_at: datetime
    expires_at: datetime


def create_access_token(*, settings: Settings, user_id: uuid.UUID, role: str) -> tuple[str, int]:
    """Return (token, expires_in_seconds)."""
    now = datetime.now(UTC)
    ttl = settings.access_token_ttl_seconds
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "role": role,
        "typ": "access",
        "jti": uuid.uuid4().hex,
        # Sub-second `iat`, deliberately. A datetime here would be encoded as
        # whole seconds, and the session cutoff compares against it: with
        # second resolution, a sign-in in the same second as a "sign out
        # everywhere" would be rejected as if it predated the revocation.
        # NumericDate permits a fractional value.
        "iat": now.timestamp(),
        "exp": now + timedelta(seconds=ttl),
        "iss": settings.app_name,
    }
    token = jwt.encode(payload, settings.secret_key.get_secret_value(), algorithm=ALGORITHM)
    return token, ttl


def decode_access_token(token: str, *, settings: Settings) -> AccessTokenClaims:
    """Verify an access token, or raise `AuthenticationError`.

    `algorithms` is pinned to one value: accepting the algorithm named in the
    token's own header is the classic JWT forgery.
    """
    try:
        payload = jwt.decode(
            token,
            settings.secret_key.get_secret_value(),
            algorithms=[ALGORITHM],
            issuer=settings.app_name,
            options={"require": ["exp", "iat", "sub"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthenticationError("Access token has expired.", code="TOKEN_EXPIRED") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthenticationError("Invalid access token.", code="TOKEN_INVALID") from exc

    if payload.get("typ") != "access":
        # A refresh token must never be usable as a bearer credential.
        raise AuthenticationError("Wrong token type.", code="TOKEN_INVALID")

    try:
        user_id = uuid.UUID(payload["sub"])
    except (KeyError, ValueError) as exc:
        raise AuthenticationError("Invalid access token.", code="TOKEN_INVALID") from exc

    return AccessTokenClaims(
        user_id=user_id,
        role=str(payload.get("role", "")),
        token_id=str(payload.get("jti", "")),
        issued_at=datetime.fromtimestamp(payload["iat"], tz=UTC),
        expires_at=datetime.fromtimestamp(payload["exp"], tz=UTC),
    )


# ----------------------------------------------------------- refresh tokens ---


def generate_refresh_token() -> tuple[str, str]:
    """Return (token, sha256_hex). Only the digest is ever stored."""
    token = secrets.token_urlsafe(REFRESH_TOKEN_BYTES)
    return token, hash_refresh_token(token)


def hash_refresh_token(token: str) -> str:
    """SHA-256 of the opaque token.

    A plain digest, not a password hash: the token already carries ~384 bits of
    entropy, so it is not brute-forceable and a slow KDF would only add latency
    to every refresh.
    """
    return hashlib.sha256(token.encode()).hexdigest()


# ------------------------------------------------------------------- misc ---


QR_TOKEN_PREFIX = "jive-ticket-v1"


def derive_qr_token(ticket_id: uuid.UUID, *, secret: str) -> str:
    """The QR payload for a ticket.

    Derived from the ticket id rather than drawn at random, which is what
    makes it **re-displayable without being stored**. The customer can reopen
    their ticket at any time and the server recomputes the same code; nothing
    re-showable sits in the database, so a disclosure yields hashes only.

    Properties this gives the ticket:

    * **stable** — the same code from purchase until the event, so a printed
      or screenshotted ticket keeps working;
    * **unguessable** — 256-bit HMAC keyed with a server secret, so knowing a
      ticket id tells an attacker nothing;
    * **single-use** — enforced on redemption, not here: the atomic check-in
      flips the ticket's status and the second scan finds nothing to update.
    """
    digest = hmac.new(
        secret.encode(), f"{QR_TOKEN_PREFIX}:{ticket_id}".encode(), hashlib.sha256
    ).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def generate_opaque_token(num_bytes: int = 32) -> str:
    """Cryptographically secure random token (QR tokens, invite links)."""
    return secrets.token_urlsafe(num_bytes)


def constant_time_equals(left: str, right: str) -> bool:
    """Compare secrets without leaking their contents through timing."""
    return secrets.compare_digest(left, right)


TokenType = Literal["access", "refresh"]
