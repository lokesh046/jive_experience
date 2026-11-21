"""User endpoints.

Self-service routes are available to any signed-in user; everything else is
administrator-only and says so in its dependency, not in a comment.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.core.pagination import Page
from app.dependencies import CurrentUser, Pagination, RequireAdmin, UserServiceDep
from app.models.user import UserRole, UserStatus
from app.schemas.user import (
    StaffCreateRequest,
    UserAdminView,
    UserProfile,
    UserProfileUpdate,
    UserStatusUpdate,
)

router = APIRouter(tags=["users"])


# ------------------------------------------------------------ self-service ---


@router.get("/me", response_model=UserProfile, summary="Your own profile")
async def read_my_profile(user: CurrentUser) -> UserProfile:
    return UserProfile.model_validate(user)


@router.patch("/me", response_model=UserProfile, summary="Update your own profile")
async def update_my_profile(
    payload: UserProfileUpdate,
    user: CurrentUser,
    service: UserServiceDep,
) -> UserProfile:
    updated = await service.update_profile(user, payload)
    return UserProfile.model_validate(updated)


# ---------------------------------------------------------- administration ---


@router.get(
    "",
    response_model=Page[UserAdminView],
    summary="List accounts (administrators only)",
)
async def list_users(
    actor: RequireAdmin,
    service: UserServiceDep,
    pagination: Pagination,
    role: Annotated[UserRole | None, Query()] = None,
    account_status: Annotated[UserStatus | None, Query(alias="status")] = None,
) -> Page[UserAdminView]:
    rows, total = await service.list_users(pagination, role=role, status=account_status)
    return Page.build(
        [UserAdminView.model_validate(row) for row in rows],
        total=total,
        params=pagination,
    )


@router.post(
    "/staff",
    response_model=UserAdminView,
    status_code=status.HTTP_201_CREATED,
    summary="Grant admin or event-staff access to a Google account",
)
async def grant_privileged_access(
    payload: StaffCreateRequest,
    actor: RequireAdmin,
    service: UserServiceDep,
) -> UserAdminView:
    """Give an email address a privileged role.

    No password is set — the person signs in with Google, and this row is what
    turns that sign-in into staff or admin access. If they already have a
    customer account, it is promoted rather than duplicated.
    """
    created = await service.grant_privileged_access(payload, actor=actor)
    return UserAdminView.model_validate(created)


@router.patch(
    "/{user_id}/status",
    response_model=UserAdminView,
    summary="Suspend, deactivate or reactivate an account (administrators only)",
)
async def set_user_status(
    user_id: uuid.UUID,
    payload: UserStatusUpdate,
    actor: RequireAdmin,
    service: UserServiceDep,
) -> UserAdminView:
    """Suspending an account ends all of its sessions immediately."""
    updated = await service.set_status(user_id, payload.status, actor=actor, reason=payload.reason)
    return UserAdminView.model_validate(updated)
