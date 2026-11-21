"""Refresh token queries."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, cast

from sqlalchemy import CursorResult, delete, update

from app.models.refresh_token import RefreshToken, TokenRevocationReason
from app.repositories.base import BaseRepository


class RefreshTokenRepository(BaseRepository[RefreshToken]):
    model = RefreshToken

    async def by_hash(self, token_hash: str) -> RefreshToken | None:
        return await self.find_one(RefreshToken.token_hash == token_hash)

    async def revoke_family(
        self,
        family_id: uuid.UUID,
        *,
        reason: TokenRevocationReason,
        at: datetime,
    ) -> int:
        """Revoke every live token descending from one login.

        Used on reuse detection: if a rotated token is presented again, the
        chain has leaked and no token in it can be trusted. One UPDATE rather
        than a load-and-loop, so the window between detection and revocation
        is as small as possible.
        """
        return await self._execute_rowcount(
            update(RefreshToken)
            .where(
                RefreshToken.family_id == family_id,
                RefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=at, revocation_reason=reason)
        )

    async def revoke_all_for_user(
        self,
        user_id: uuid.UUID,
        *,
        reason: TokenRevocationReason,
        at: datetime,
    ) -> int:
        """Sign the user out everywhere (logout-all, suspension, password change)."""
        return await self._execute_rowcount(
            update(RefreshToken)
            .where(
                RefreshToken.user_id == user_id,
                RefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=at, revocation_reason=reason)
        )

    async def delete_expired(self, *, before: datetime) -> int:
        """Housekeeping for the scheduler: drop long-dead rows."""
        return await self._execute_rowcount(
            delete(RefreshToken).where(RefreshToken.expires_at < before)
        )

    async def _execute_rowcount(self, statement: Any) -> int:
        """Run a bulk UPDATE/DELETE and return the number of rows affected."""
        result = cast("CursorResult[Any]", await self.session.execute(statement))
        return result.rowcount or 0
