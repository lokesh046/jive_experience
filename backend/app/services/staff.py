"""Event staff assignments.

Separate from account creation (which is `UserService`): being EVENT_STAFF is
an account property, but being allowed to scan *this* event is an assignment.
Both are checked at the gate.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import BusinessRuleError, ConflictError, NotFoundError
from app.models.event import PUBLIC_EVENT_STATUSES, Event
from app.models.fulfilment import StaffEventAssignment
from app.models.user import User, UserRole, UserStatus
from app.repositories.catalogue import EventRepository
from app.repositories.fulfilment import StaffAssignmentRepository
from app.repositories.user import UserRepository
from app.services.audit import AuditService

logger = structlog.get_logger(__name__)


class StaffService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.assignments = StaffAssignmentRepository(session)
        self.users = UserRepository(session)
        self.events = EventRepository(session)
        self.audit = AuditService(session)

    async def assign(
        self, *, user_id: uuid.UUID, event_id: uuid.UUID, actor: User
    ) -> StaffEventAssignment:
        """Put a staff member on an event."""
        member = await self.users.get_or_fail(user_id)
        if member.role is not UserRole.EVENT_STAFF:
            raise BusinessRuleError(
                "Only event-staff accounts can be assigned to events.",
                code="NOT_EVENT_STAFF",
            )
        if member.status is not UserStatus.ACTIVE:
            raise BusinessRuleError("This staff account is not active.", code="STAFF_NOT_ACTIVE")

        event = await self.events.get(event_id)
        if event is None:
            raise NotFoundError("Event not found.", code="EVENT_NOT_FOUND")

        existing = await self.assignments.existing(user_id, event_id)
        if existing is not None:
            if existing.revoked_at is None:
                raise ConflictError(
                    "This staff member is already assigned to the event.",
                    code="ALREADY_ASSIGNED",
                )
            # Re-assigning after a revoke reuses the row: the unique
            # constraint on (user, event) means there is only ever one.
            existing.revoked_at = None
            existing.assigned_by_id = actor.id
            assignment = existing
        else:
            # `user=member` as well as the id: the response reads assignment.user, and a
            # brand-new row has no loaded relationship (lazy loading is not possible here).
            assignment = StaffEventAssignment(
                user_id=user_id, event_id=event_id, assigned_by_id=actor.id, user=member
            )
            self.assignments.add(assignment)

        await self.session.flush()
        await self.audit.record(
            "staff.assigned",
            entity_type="staff_event_assignment",
            entity_id=assignment.id,
            actor=actor,
            after={"user_id": str(user_id), "event_id": str(event_id)},
        )
        await self.session.commit()
        logger.info("staff_assigned", user_id=str(user_id), event_id=str(event_id))
        return assignment

    async def revoke(self, *, user_id: uuid.UUID, event_id: uuid.UUID, actor: User) -> None:
        """Take a staff member off an event.

        Soft revoke, so the scan history keeps pointing at a real assignment
        record.
        """
        assignment = await self.assignments.existing(user_id, event_id)
        if assignment is None or assignment.revoked_at is not None:
            raise NotFoundError("Assignment not found.", code="ASSIGNMENT_NOT_FOUND")

        assignment.revoked_at = datetime.now(UTC)
        await self.audit.record(
            "staff.unassigned",
            entity_type="staff_event_assignment",
            entity_id=assignment.id,
            actor=actor,
            before={"user_id": str(user_id), "event_id": str(event_id)},
        )
        await self.session.commit()
        logger.info("staff_unassigned", user_id=str(user_id), event_id=str(event_id))

    async def for_event(self, event_id: uuid.UUID) -> Sequence[StaffEventAssignment]:
        return await self.assignments.for_event(event_id)

    async def my_events(self, staff: User) -> Sequence[StaffEventAssignment]:
        """Assignments for a staff member, newest first."""
        return await self.assignments.for_user(staff.id)

    async def scannable_events(self, staff: User) -> list[Event]:
        """The scanner's event picker, soonest first.

        A staff member sees only the events they are assigned to; an administrator may scan any
        live event, so sees all of them. Cancelled and draft events never appear, and an event
        stays listed until the morning after it was held, so a late night is not cut off.
        """
        since = datetime.now(UTC) - timedelta(hours=24)
        if staff.role is UserRole.ADMIN:
            return list(await self.events.for_scanning(since))
        assigned = [a.event for a in await self.assignments.for_user(staff.id)]
        live = [e for e in assigned if e.status in PUBLIC_EVENT_STATUSES and e.starts_at >= since]
        return sorted(live, key=lambda e: e.starts_at)
