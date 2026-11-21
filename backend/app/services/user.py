"""User account rules."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import BusinessRuleError, ConflictError
from app.core.pagination import PageParams
from app.models.refresh_token import TokenRevocationReason
from app.models.user import User, UserRole, UserStatus
from app.repositories.refresh_token import RefreshTokenRepository
from app.repositories.user import UserRepository
from app.schemas.user import StaffCreateRequest, UserProfileUpdate
from app.services.audit import AuditService

logger = structlog.get_logger(__name__)


class UserService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.users = UserRepository(session)
        self.tokens = RefreshTokenRepository(session)
        self.audit = AuditService(session)

    # ------------------------------------------------------------ profile ---

    async def update_profile(self, user: User, payload: UserProfileUpdate) -> User:
        """Update the caller's own profile.

        The email address is not editable here: for a customer it is what
        Google asserts, and letting it be changed freely would let one account
        claim another's identity. The phone number has its own endpoint
        because it is verified.
        """
        if payload.full_name is not None:
            user.full_name = payload.full_name

        await self.session.commit()
        return user

    # ------------------------------------------------- administration ----

    async def grant_privileged_access(self, payload: StaffCreateRequest, *, actor: User) -> User:
        """Give a Google account administrator or event-staff access.

        This is the whole permission model for privileged roles: the row is
        created here with the role, and the person gets it the next time they
        sign in with Google under that email. There is no password, no invite
        token and no self-service path — which means there is also nothing to
        phish, leak or reset.

        If the address already belongs to a customer (they booked tickets
        before being given access), the existing account is promoted rather
        than duplicated: a second row would fail the unique constraint on
        email and would orphan their booking history.
        """
        email = str(payload.email).lower()
        existing = await self.users.by_email(email)

        if existing is not None:
            if existing.is_privileged:
                raise ConflictError(
                    "That email already has staff access.", code="ALREADY_PRIVILEGED"
                )
            previous_role = existing.role
            existing.role = payload.role
            existing.status = UserStatus.ACTIVE
            # Their current tokens carry the old role. Force a fresh sign-in
            # so nothing is running with a stale claim.
            existing.sessions_valid_from = datetime.now(UTC)
            if payload.full_name:
                existing.full_name = payload.full_name.strip()

            await self.audit.record(
                "user.role_granted",
                entity_type="user",
                entity_id=existing.id,
                actor=actor,
                before={"role": previous_role.value},
                after={"role": payload.role.value, "email": email},
            )
            await self.session.commit()
            logger.info(
                "existing_account_promoted",
                user_id=str(existing.id),
                role=payload.role.value,
            )
            return existing

        user = User(
            role=payload.role,
            status=UserStatus.ACTIVE,
            email=email,
            full_name=payload.full_name.strip(),
        )
        self.users.add(user)
        await self.session.flush()

        await self.audit.record(
            "user.created",
            entity_type="user",
            entity_id=user.id,
            actor=actor,
            after={"email": email, "role": payload.role.value},
        )
        await self.session.commit()
        logger.info("privileged_user_created", user_id=str(user.id), role=payload.role.value)
        return user

    async def set_status(
        self,
        user_id: uuid.UUID,
        status: UserStatus,
        *,
        actor: User,
        reason: str | None = None,
    ) -> User:
        """Suspend, deactivate or reactivate an account.

        Suspension ends every live session immediately — leaving a suspended
        user with a working refresh token would make the suspension advisory.
        """
        if user_id == actor.id:
            raise BusinessRuleError(
                "You cannot change your own account status.",
                code="CANNOT_MODIFY_SELF",
            )

        target = await self.users.get_or_fail(user_id)
        previous = target.status
        if previous is status:
            return target

        now = datetime.now(UTC)
        target.status = status
        if status is not UserStatus.ACTIVE:
            await self.tokens.revoke_all_for_user(
                target.id,
                reason=TokenRevocationReason.ACCOUNT_SUSPENDED,
                at=now,
            )
            # Belt and braces: the status check in `get_current_user` already
            # blocks this account, but the cutoff means any token it holds is
            # dead even if the status is later restored.
            target.sessions_valid_from = now

        await self.audit.record(
            "user.status_changed",
            entity_type="user",
            entity_id=target.id,
            actor=actor,
            before={"status": previous.value},
            after={"status": status.value, "reason": reason},
        )
        await self.session.commit()
        logger.info(
            "user_status_changed",
            user_id=str(target.id),
            before=previous.value,
            after=status.value,
        )
        return target

    async def list_users(
        self,
        params: PageParams,
        *,
        role: UserRole | None = None,
        status: UserStatus | None = None,
    ) -> tuple[Sequence[User], int]:
        where = []
        if role is not None:
            where.append(User.role == role)
        if status is not None:
            where.append(User.status == status)
        return await self.users.paginate(params, *where, order_by=[User.created_at.desc()])
