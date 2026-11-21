"""Authentication business rules.

**One sign-in path for everyone.** Customers, event staff and administrators
all authenticate with Google OAuth 2.0; there are no passwords in this system.

The distinction between them is the *row*, not the credential. A privileged
account exists because an administrator created it with that email address
before the person first signed in. Google proves identity; the database
decides authority. Nothing in this module can raise a role.
"""

from __future__ import annotations

import json
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import structlog
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import (
    AuthenticationError,
    ConflictError,
    PermissionDeniedError,
)
from app.core.security import (
    create_access_token,
    generate_refresh_token,
    hash_refresh_token,
)
from app.models.refresh_token import RefreshToken, TokenRevocationReason
from app.models.user import User, UserRole, UserStatus
from app.repositories.refresh_token import RefreshTokenRepository
from app.repositories.user import UserRepository
from app.services.google_oauth import (
    AuthorizationRequest,
    GoogleIdentity,
    GoogleOAuthClient,
    generate_pkce_pair,
)

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class RequestContext:
    """Where a session was created from, for the session list and audit trail."""

    ip_address: str | None = None
    user_agent: str | None = None


@dataclass(frozen=True, slots=True)
class IssuedTokens:
    access_token: str
    refresh_token: str
    expires_in: int
    user: User


OAUTH_STATE_PREFIX = "oauth:google:state"


class AuthService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        google: GoogleOAuthClient,
        redis: Redis,
    ) -> None:
        self.session = session
        self.settings = settings
        self.google = google
        self.redis = redis
        self.users = UserRepository(session)
        self.tokens = RefreshTokenRepository(session)

    # ------------------------------------------------ customer Google login ---

    async def start_google_sign_in(self, redirect_uri: str | None = None) -> AuthorizationRequest:
        """Begin the OAuth flow.

        The `state` and the PKCE verifier are held in Redis rather than in a
        cookie so the same flow works for the web app and for a mobile client,
        neither of which shares a cookie jar with the API.
        """
        state = secrets.token_urlsafe(32)
        verifier, challenge = generate_pkce_pair()
        target = redirect_uri or self.settings.google_redirect_uri

        await self.redis.set(
            f"{OAUTH_STATE_PREFIX}:{state}",
            json.dumps({"verifier": verifier, "redirect_uri": target}),
            ex=self.settings.oauth_state_ttl_seconds,
        )

        return AuthorizationRequest(
            authorization_url=self.google.build_authorization_url(
                state=state, code_challenge=challenge, redirect_uri=target
            ),
            state=state,
        )

    async def complete_google_sign_in(
        self,
        *,
        code: str,
        state: str,
        context: RequestContext | None = None,
    ) -> IssuedTokens:
        """Finish the OAuth flow and issue application tokens.

        Creates the customer on first sign-in. This path can only ever produce
        a CUSTOMER: it sets no password hash, and the database CHECK constraint
        rejects a privileged row without one.
        """
        pending = await self._consume_state(state)

        id_token = await self.google.exchange_code(
            code=code,
            code_verifier=pending["verifier"],
            redirect_uri=pending["redirect_uri"],
        )
        identity = await self.google.verify_id_token(id_token)

        if not identity.email_verified:
            # An unverified Google email could belong to someone else, which
            # would let an attacker claim an existing account by email.
            raise AuthenticationError(
                "Your Google email address is not verified.",
                code="GOOGLE_EMAIL_UNVERIFIED",
            )

        user = await self.users.by_google_sub(identity.subject)
        if user is None:
            user = await self._link_or_create_user(identity)

        self._assert_account_usable(user)

        user.google_sub = identity.subject
        user.email = identity.email
        if user.email_verified_at is None:
            user.email_verified_at = datetime.now(UTC)
        if identity.full_name and not user.full_name:
            user.full_name = identity.full_name
        if identity.picture:
            user.avatar_url = identity.picture

        issued, _ = await self._issue(user, context=context, new_session=True)
        return issued

    async def _consume_state(self, state: str) -> dict[str, str]:
        """Validate and single-use the pending sign-in.

        Deleting on read is what makes the authorization code single-use from
        our side too: a replayed callback finds nothing and is refused.
        """
        key = f"{OAUTH_STATE_PREFIX}:{state}"
        raw = await self.redis.get(key)
        if raw is None:
            raise AuthenticationError(
                "This sign-in link has expired or was already used. Please try again.",
                code="OAUTH_STATE_INVALID",
            )
        await self.redis.delete(key)
        stored: dict[str, str] = json.loads(raw)
        return stored

    async def _link_or_create_user(self, identity: GoogleIdentity) -> User:
        """Find the account for this verified email, or create a customer.

        This is where an administrator or staff member's access actually comes
        from. Their row was created in advance with the right role and no
        `google_sub`; the first time they sign in, the verified email matches
        and the Google identity is linked to that existing row. They keep the
        role they were given.

        If no row exists, a CUSTOMER is created. That is the only role this
        path can ever produce — signing in cannot grant authority, and there
        is no branch here that reads a role from anything the caller supplied.
        """
        existing = await self.users.by_email(identity.email)
        if existing is not None:
            if existing.is_privileged:
                logger.info(
                    "privileged_sign_in",
                    user_id=str(existing.id),
                    role=existing.role.value,
                    first_sign_in=not existing.has_signed_in,
                )
            return existing

        user = User(
            role=UserRole.CUSTOMER,
            status=UserStatus.ACTIVE,
            email=identity.email,
            google_sub=identity.subject,
            full_name=identity.full_name,
            avatar_url=identity.picture,
            email_verified_at=datetime.now(UTC),
        )
        self.users.add(user)
        await self.session.flush()
        logger.info("customer_registered", user_id=str(user.id))
        return user

    async def set_phone_number(self, user: User, phone_e164: str) -> User:
        """Attach a phone number to an account.

        Google accounts are free and unlimited, so the phone number is what
        makes a per-account purchase limit meaningful. Phase 4 requires one
        before a reservation; see docs/anti-bot.md.
        """
        allowed = self.settings.allowed_phone_country_codes
        if allowed and not any(phone_e164.startswith(code) for code in allowed):
            raise PermissionDeniedError(
                "Bookings are not available for this country.",
                code="PHONE_COUNTRY_NOT_ALLOWED",
            )

        taken = await self.users.by_phone(phone_e164)
        if taken is not None and taken.id != user.id:
            raise ConflictError(
                "That phone number is already registered to another account.",
                code="PHONE_TAKEN",
            )

        user.phone_e164 = phone_e164
        await self.session.commit()
        return user

    # ------------------------------------------------------------ refresh ---

    async def refresh(
        self, presented_token: str, *, context: RequestContext | None = None
    ) -> IssuedTokens:
        """Rotate a refresh token.

        Reuse detection: a token that has already been rotated must never work
        again. If one is presented, the chain has leaked — every live token in
        that family is revoked, forcing a fresh login on the real user and
        locking out the thief.
        """
        stored = await self.tokens.by_hash(hash_refresh_token(presented_token))
        now = datetime.now(UTC)

        if stored is None:
            raise AuthenticationError("Invalid refresh token.", code="REFRESH_INVALID")

        if stored.revoked_at is not None:
            revoked = await self.tokens.revoke_family(
                stored.family_id,
                reason=TokenRevocationReason.REUSE_DETECTED,
                at=now,
            )
            await self.session.commit()
            logger.warning(
                "refresh_token_reuse_detected",
                user_id=str(stored.user_id),
                family_id=str(stored.family_id),
                revoked_tokens=revoked,
            )
            raise AuthenticationError(
                "This session has been ended for security reasons. Please sign in again.",
                code="REFRESH_REUSED",
            )

        if stored.expires_at <= now:
            raise AuthenticationError("Refresh token has expired.", code="REFRESH_EXPIRED")

        user = await self.users.get(stored.user_id)
        if user is None:  # pragma: no cover - FK cascade makes this unreachable
            raise AuthenticationError("Invalid refresh token.", code="REFRESH_INVALID")
        self._assert_account_usable(user)

        # Claim the token before minting anything. Checking `revoked_at` and
        # then writing it let two simultaneous refreshes both pass the check
        # and both issue a replacement — one credential becoming two live
        # sessions, and the rotation chain that reuse detection relies on
        # quietly forking into two.
        if not await self.tokens.claim_for_rotation(stored.id, now=now):
            # Another request rotated it microseconds ago. Deliberately *not*
            # treated as reuse: a double-tapped button is not theft, and
            # revoking the family would sign the customer out for it. The
            # other response carries the new pair.
            await self.session.commit()
            logger.info("refresh_race_lost", user_id=str(stored.user_id))
            raise AuthenticationError(
                "This token was just refreshed. Please retry with the new one.",
                code="REFRESH_IN_PROGRESS",
            )

        issued, replacement = await self._issue(
            user, context=context, new_session=False, family_id=stored.family_id
        )
        stored.replaced_by_id = replacement.id
        await self.session.commit()
        return issued

    # ------------------------------------------------------------- logout ---

    async def logout(self, presented_token: str) -> None:
        """End one session. Unknown tokens succeed silently — logout should
        never be an oracle for which tokens exist."""
        stored = await self.tokens.by_hash(hash_refresh_token(presented_token))
        if stored is not None and stored.revoked_at is None:
            stored.revoked_at = datetime.now(UTC)
            stored.revocation_reason = TokenRevocationReason.LOGOUT
        await self.session.commit()

    async def logout_everywhere(self, user: User) -> int:
        """End every session for this user, including live access tokens.

        Revoking the refresh tokens alone would leave any access token working
        until it expired — up to fifteen minutes of access after the person
        pressed "sign out everywhere", which is exactly the window someone
        reaching for that button is trying to close. Setting the cutoff makes
        it immediate.
        """
        now = datetime.now(UTC)
        count = await self.tokens.revoke_all_for_user(
            user.id, reason=TokenRevocationReason.LOGOUT, at=now
        )
        user.sessions_valid_from = now
        await self.session.commit()
        return count

    # -------------------------------------------------------------- shared ---

    def _assert_account_usable(self, user: User) -> None:
        if user.status is UserStatus.SUSPENDED:
            raise PermissionDeniedError(
                "This account has been suspended.", code="ACCOUNT_SUSPENDED"
            )
        if user.status is UserStatus.DEACTIVATED:
            raise AuthenticationError(
                "This account is no longer active.", code="ACCOUNT_DEACTIVATED"
            )

    async def _issue(
        self,
        user: User,
        *,
        context: RequestContext | None,
        new_session: bool,
        family_id: uuid.UUID | None = None,
    ) -> tuple[IssuedTokens, RefreshToken]:
        """Mint an access token and a stored refresh token.

        Returns the stored row as well so the caller can link a rotation
        (`replaced_by_id`) without the service holding hidden state.
        """
        now = datetime.now(UTC)
        access_token, expires_in = create_access_token(
            settings=self.settings, user_id=user.id, role=user.role.value
        )
        refresh_value, refresh_hash = generate_refresh_token()

        record = RefreshToken(
            user_id=user.id,
            token_hash=refresh_hash,
            family_id=family_id or uuid.uuid4(),
            expires_at=now + timedelta(seconds=self.settings.refresh_token_ttl_seconds),
            user_agent=(context.user_agent if context else None),
            ip_address=(context.ip_address if context else None),
        )
        self.tokens.add(record)
        await self.session.flush()

        if new_session:
            user.last_login_at = now
            await self.session.commit()

        return (
            IssuedTokens(
                access_token=access_token,
                refresh_token=refresh_value,
                expires_in=expires_in,
                user=user,
            ),
            record,
        )
