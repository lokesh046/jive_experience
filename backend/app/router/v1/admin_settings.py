"""Administrator settings: the default cancellation and refund policy."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.dependencies import RequireAdmin, SettingsServiceDep
from app.schemas.policy import CancellationPolicy, DefaultPolicyIn, DefaultPolicyOut

router = APIRouter(tags=["admin: settings"])


@router.get(
    "/settings/cancellation-policy",
    response_model=DefaultPolicyOut,
    summary="The default refund policy",
)
async def get_default_policy(actor: RequireAdmin, service: SettingsServiceDep) -> DefaultPolicyOut:
    stored = await service.default_policy()
    return DefaultPolicyOut(policy=CancellationPolicy.model_validate(stored) if stored else None)


@router.put(
    "/settings/cancellation-policy",
    response_model=DefaultPolicyOut,
    summary="Set the default refund policy",
)
async def set_default_policy(
    payload: DefaultPolicyIn, actor: RequireAdmin, service: SettingsServiceDep
) -> DefaultPolicyOut:
    """Used by every event that has no policy of its own. `null` clears it."""
    await service.set_default_policy(payload.policy, actor=actor)
    return DefaultPolicyOut(
        policy=payload.policy if payload.policy and payload.policy.tiers else None
    )


class EmailSettings(BaseModel):
    abandoned_emails: bool


@router.get("/settings/emails", response_model=EmailSettings, summary="Automatic emails")
async def get_email_settings(actor: RequireAdmin, service: SettingsServiceDep) -> EmailSettings:
    return EmailSettings(abandoned_emails=await service.abandoned_emails())


@router.put("/settings/emails", response_model=EmailSettings, summary="Switch automatic emails")
async def set_email_settings(
    payload: EmailSettings, actor: RequireAdmin, service: SettingsServiceDep
) -> EmailSettings:
    """Today: the one-time "you left before paying" email."""
    await service.set_abandoned_emails(payload.abandoned_emails, actor=actor)
    return payload
