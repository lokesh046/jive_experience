"""Recording sensitive actions.

Append-only. Nothing in the application updates or deletes an audit row.

The row is staged in the **caller's transaction**, so the trail and the change
it describes commit or roll back together — an action that was rolled back must
not leave an audit entry claiming it happened.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog
from app.models.user import User
from app.repositories.audit_log import AuditLogRepository

# Keys whose values are never written to the trail, at any nesting level.
REDACTED_KEYS = frozenset(
    {
        "password",
        "new_password",
        "current_password",
        "password_hash",
        "token",
        "access_token",
        "refresh_token",
        "id_token",
        "client_secret",
        "code_verifier",
        "token_hash",
        "secret",
        "api_key",
        "card",
        "cvv",
    }
)
REDACTED = "[redacted]"


def redact(data: dict[str, Any] | None) -> dict[str, Any] | None:
    """Strip secrets from a snapshot before it is stored."""
    if data is None:
        return None
    cleaned: dict[str, Any] = {}
    for key, value in data.items():
        if key.lower() in REDACTED_KEYS:
            cleaned[key] = REDACTED
        elif isinstance(value, dict):
            cleaned[key] = redact(value)
        else:
            cleaned[key] = value
    return cleaned


class AuditService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.logs = AuditLogRepository(session)

    async def record(
        self,
        action: str,
        *,
        entity_type: str,
        entity_id: str | uuid.UUID | None = None,
        actor: User | None = None,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
        request_id: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> AuditLog:
        """Stage an audit entry. The caller commits.

        `action` is a dotted verb — "event.published", "refund.initiated",
        "staff.created".
        """
        entry = AuditLog(
            actor_user_id=actor.id if actor else None,
            actor_role=actor.role.value if actor else None,
            actor_label=(actor.full_name or actor.email or actor.phone_e164) if actor else None,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id is not None else None,
            before=redact(before),
            after=redact(after),
            context=redact(context),
            request_id=request_id,
            ip_address=ip_address,
            user_agent=user_agent[:400] if user_agent else None,
        )
        self.logs.add(entry)
        return entry
