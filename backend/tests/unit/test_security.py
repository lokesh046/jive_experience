(
    """Access-token handling.

There are no password tests because there are no passwords: every account
signs in with Google OAuth 2.0.
"""
    ""
)

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pytest

from app.core.config import Settings
from app.core.errors import AuthenticationError
from app.core.security import (
    ALGORITHM,
    create_access_token,
    decode_access_token,
    generate_refresh_token,
    hash_refresh_token,
)


@pytest.fixture
def settings() -> Settings:
    return Settings(secret_key="u" * 64, app_name="JIVE Events API")


# ------------------------------------------------------------- access tokens ---


def test_access_token_round_trip(settings: Settings) -> None:
    user_id = uuid.uuid4()
    token, expires_in = create_access_token(settings=settings, user_id=user_id, role="ADMIN")

    claims = decode_access_token(token, settings=settings)
    assert claims.user_id == user_id
    assert claims.role == "ADMIN"
    assert expires_in == settings.access_token_ttl_seconds


def test_token_signed_with_another_key_is_rejected(settings: Settings) -> None:
    token, _ = create_access_token(settings=settings, user_id=uuid.uuid4(), role="CUSTOMER")
    other = Settings(secret_key="d" * 64, app_name=settings.app_name)

    with pytest.raises(AuthenticationError) as excinfo:
        decode_access_token(token, settings=other)
    assert excinfo.value.code == "TOKEN_INVALID"


def test_expired_token_is_reported_distinctly(settings: Settings) -> None:
    """Clients retry on TOKEN_EXPIRED but must not retry on TOKEN_INVALID."""
    past = datetime.now(UTC) - timedelta(hours=2)
    payload: dict[str, Any] = {
        "sub": str(uuid.uuid4()),
        "role": "CUSTOMER",
        "typ": "access",
        "jti": uuid.uuid4().hex,
        "iat": past,
        "exp": past + timedelta(minutes=15),
        "iss": settings.app_name,
    }
    token = jwt.encode(payload, settings.secret_key.get_secret_value(), algorithm=ALGORITHM)

    with pytest.raises(AuthenticationError) as excinfo:
        decode_access_token(token, settings=settings)
    assert excinfo.value.code == "TOKEN_EXPIRED"


def test_alg_none_forgery_is_rejected(settings: Settings) -> None:
    """The classic JWT attack: an unsigned token claiming alg=none."""
    forged = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "role": "ADMIN",
            "typ": "access",
            "iat": datetime.now(UTC),
            "exp": datetime.now(UTC) + timedelta(hours=1),
            "iss": settings.app_name,
        },
        key="",
        algorithm="none",
    )

    with pytest.raises(AuthenticationError):
        decode_access_token(forged, settings=settings)


def test_token_from_another_issuer_is_rejected(settings: Settings) -> None:
    token = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "role": "ADMIN",
            "typ": "access",
            "iat": datetime.now(UTC),
            "exp": datetime.now(UTC) + timedelta(hours=1),
            "iss": "some-other-service",
        },
        settings.secret_key.get_secret_value(),
        algorithm=ALGORITHM,
    )

    with pytest.raises(AuthenticationError):
        decode_access_token(token, settings=settings)


def test_a_refresh_token_cannot_be_used_as_a_bearer_token(settings: Settings) -> None:
    """Token type confusion: a long-lived credential must not authorise calls."""
    token = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "role": "ADMIN",
            "typ": "refresh",
            "iat": datetime.now(UTC),
            "exp": datetime.now(UTC) + timedelta(days=30),
            "iss": settings.app_name,
        },
        settings.secret_key.get_secret_value(),
        algorithm=ALGORITHM,
    )

    with pytest.raises(AuthenticationError) as excinfo:
        decode_access_token(token, settings=settings)
    assert excinfo.value.code == "TOKEN_INVALID"


def test_garbage_is_rejected(settings: Settings) -> None:
    for value in ("", "not.a.token", "a.b.c"):
        with pytest.raises(AuthenticationError):
            decode_access_token(value, settings=settings)


# ------------------------------------------------------------ refresh tokens ---


def test_refresh_tokens_are_unique_and_only_the_digest_is_storable() -> None:
    token_a, hash_a = generate_refresh_token()
    token_b, hash_b = generate_refresh_token()

    assert token_a != token_b
    assert hash_a != hash_b
    assert hash_a == hash_refresh_token(token_a)
    assert len(hash_a) == 64, "sha256 hex digest"
    assert token_a not in hash_a, "the digest must not contain the token"


def test_refresh_token_has_substantial_entropy() -> None:
    token, _ = generate_refresh_token()
    assert len(token) >= 60
