"""Google OAuth client: PKCE, the authorization URL, and ID token verification.

Token verification is tested with a locally generated RSA key standing in for
Google's, so the whole path — signature, audience, issuer, expiry — is
exercised without the network.
"""

from __future__ import annotations

import base64
import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.core.config import Settings
from app.core.errors import AuthenticationError, ServiceUnavailableError
from app.services.google_oauth import (
    AUTHORIZATION_ENDPOINT,
    GoogleOAuthClient,
    generate_pkce_pair,
)

CLIENT_ID = "test-client.apps.googleusercontent.com"
REDIRECT_URI = "https://jive.example.com/auth/google/callback"
KID = "test-key-1"


@pytest.fixture(scope="module")
def signing_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def settings() -> Settings:
    return Settings(
        google_client_id=CLIENT_ID,
        google_client_secret="test-secret",
        google_redirect_uri=REDIRECT_URI,
    )


@pytest.fixture
def client(
    settings: Settings, signing_key: rsa.RSAPrivateKey, monkeypatch: pytest.MonkeyPatch
) -> GoogleOAuthClient:
    """A client whose JWKS is our local public key rather than Google's."""
    oauth = GoogleOAuthClient(settings)

    async def fake_signing_key(kid: str | None) -> Any:
        if kid != KID:
            raise AuthenticationError("Invalid Google identity token.", code="GOOGLE_TOKEN_INVALID")
        return signing_key.public_key()

    monkeypatch.setattr(oauth, "_signing_key", fake_signing_key)
    return oauth


def make_id_token(signing_key: rsa.RSAPrivateKey, **overrides: Any) -> str:
    now = datetime.now(UTC)
    claims: dict[str, Any] = {
        "iss": "https://accounts.google.com",
        "aud": CLIENT_ID,
        "sub": "1234567890",
        "email": "Asha@Example.com",
        "email_verified": True,
        "name": "Asha Rao",
        "picture": "https://example.com/a.png",
        "iat": now,
        "exp": now + timedelta(hours=1),
    }
    claims.update(overrides)
    return jwt.encode(claims, signing_key, algorithm="RS256", headers={"kid": KID})


# ------------------------------------------------------------------- PKCE ---


def test_pkce_challenge_is_the_s256_of_the_verifier() -> None:
    verifier, challenge = generate_pkce_pair()

    expected = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )
    assert challenge == expected
    assert "=" not in challenge, "base64url for PKCE is unpadded"


def test_pkce_pairs_are_unique() -> None:
    first, _ = generate_pkce_pair()
    second, _ = generate_pkce_pair()
    assert first != second


def test_pkce_verifier_length_is_within_the_spec() -> None:
    verifier, _ = generate_pkce_pair()
    assert 43 <= len(verifier) <= 128


# ------------------------------------------------------ authorization URL ---


def test_authorization_url_carries_the_required_parameters(
    client: GoogleOAuthClient,
) -> None:
    url = client.build_authorization_url(
        state="the-state", code_challenge="the-challenge", redirect_uri=REDIRECT_URI
    )

    assert url.startswith(AUTHORIZATION_ENDPOINT)
    for fragment in (
        f"client_id={CLIENT_ID}",
        "response_type=code",
        "state=the-state",
        "code_challenge=the-challenge",
        "code_challenge_method=S256",
        "scope=openid+email+profile",
    ):
        assert fragment in url, fragment


def test_authorization_url_never_contains_the_client_secret(
    client: GoogleOAuthClient,
) -> None:
    url = client.build_authorization_url(state="s", code_challenge="c", redirect_uri=REDIRECT_URI)
    assert "test-secret" not in url


def test_unconfigured_client_refuses_rather_than_guessing() -> None:
    oauth = GoogleOAuthClient(Settings(google_client_id=None, google_client_secret=None))

    with pytest.raises(ServiceUnavailableError) as excinfo:
        oauth.build_authorization_url(state="s", code_challenge="c", redirect_uri="x")
    assert excinfo.value.code == "GOOGLE_NOT_CONFIGURED"


# ---------------------------------------------------- ID token verification ---


async def test_valid_id_token_yields_the_identity(
    client: GoogleOAuthClient, signing_key: rsa.RSAPrivateKey
) -> None:
    identity = await client.verify_id_token(make_id_token(signing_key))

    assert identity.subject == "1234567890"
    assert identity.email == "asha@example.com", "email is normalised to lowercase"
    assert identity.email_verified is True
    assert identity.full_name == "Asha Rao"


async def test_token_for_another_client_is_rejected(
    client: GoogleOAuthClient, signing_key: rsa.RSAPrivateKey
) -> None:
    """A token minted for a different app must not authenticate here —
    this is the confused-deputy attack on OAuth sign-in."""
    token = make_id_token(signing_key, aud="someone-elses-client-id")

    with pytest.raises(AuthenticationError) as excinfo:
        await client.verify_id_token(token)
    assert excinfo.value.code == "GOOGLE_TOKEN_INVALID"


async def test_token_from_another_issuer_is_rejected(
    client: GoogleOAuthClient, signing_key: rsa.RSAPrivateKey
) -> None:
    token = make_id_token(signing_key, iss="https://evil.example.com")

    with pytest.raises(AuthenticationError):
        await client.verify_id_token(token)


async def test_expired_token_is_rejected(
    client: GoogleOAuthClient, signing_key: rsa.RSAPrivateKey
) -> None:
    past = datetime.now(UTC) - timedelta(hours=2)
    token = make_id_token(signing_key, iat=past, exp=past + timedelta(minutes=5))

    with pytest.raises(AuthenticationError) as excinfo:
        await client.verify_id_token(token)
    assert excinfo.value.code == "GOOGLE_TOKEN_EXPIRED"


async def test_token_signed_by_an_unknown_key_is_rejected(
    client: GoogleOAuthClient,
) -> None:
    attacker_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = jwt.encode(
        {
            "iss": "https://accounts.google.com",
            "aud": CLIENT_ID,
            "sub": "attacker",
            "email": "attacker@example.com",
            "email_verified": True,
            "iat": datetime.now(UTC),
            "exp": datetime.now(UTC) + timedelta(hours=1),
        },
        attacker_key,
        algorithm="RS256",
        headers={"kid": "not-googles-key"},
    )

    with pytest.raises(AuthenticationError):
        await client.verify_id_token(token)


async def test_token_without_an_email_is_rejected(
    client: GoogleOAuthClient, signing_key: rsa.RSAPrivateKey
) -> None:
    token = make_id_token(signing_key, email=None)

    with pytest.raises(AuthenticationError) as excinfo:
        await client.verify_id_token(token)
    assert excinfo.value.code == "GOOGLE_EMAIL_REQUIRED"


async def test_unverified_email_is_reported_not_silently_trusted(
    client: GoogleOAuthClient, signing_key: rsa.RSAPrivateKey
) -> None:
    """The client reports the flag; the service decides to refuse."""
    identity = await client.verify_id_token(make_id_token(signing_key, email_verified=False))
    assert identity.email_verified is False


async def test_garbage_is_rejected(client: GoogleOAuthClient) -> None:
    for value in ("", "not.a.token", "a.b.c"):
        with pytest.raises(AuthenticationError):
            await client.verify_id_token(value)
