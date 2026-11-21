"""Google OAuth stub.

Stands in for Google's token and certificate endpoints so the authentication
tests need no network and no real client credentials. Only the two calls the
service makes are implemented.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core.errors import AuthenticationError
from app.services.google_oauth import GoogleIdentity


@dataclass
class StubGoogleClient:
    """Replaces `GoogleOAuthClient` in tests.

    Tests register the authorization codes they consider valid; anything else
    is refused exactly as Google would refuse a replayed or forged code.
    """

    identities: dict[str, GoogleIdentity] = field(default_factory=dict)
    consumed_codes: list[str] = field(default_factory=list)
    configured: bool = True

    def register(
        self,
        code: str,
        *,
        subject: str,
        email: str,
        email_verified: bool = True,
        full_name: str | None = None,
        picture: str | None = None,
    ) -> str:
        self.identities[code] = GoogleIdentity(
            subject=subject,
            email=email.lower(),
            email_verified=email_verified,
            full_name=full_name,
            picture=picture,
        )
        return code

    def build_authorization_url(self, *, state: str, code_challenge: str, redirect_uri: str) -> str:
        return (
            "https://accounts.google.com/o/oauth2/v2/auth"
            f"?state={state}&code_challenge={code_challenge}&redirect_uri={redirect_uri}"
        )

    async def exchange_code(self, *, code: str, code_verifier: str, redirect_uri: str) -> str:
        """Google rejects a code that was already exchanged; so does this."""
        if code in self.consumed_codes or code not in self.identities:
            raise AuthenticationError(
                "Google sign-in could not be completed. Please try again.",
                code="GOOGLE_CODE_INVALID",
            )
        self.consumed_codes.append(code)
        # The "ID token" is just the code again; verify_id_token looks it up.
        return code

    async def verify_id_token(self, id_token: str) -> GoogleIdentity:
        identity = self.identities.get(id_token)
        if identity is None:
            raise AuthenticationError("Invalid Google identity token.", code="GOOGLE_TOKEN_INVALID")
        return identity
