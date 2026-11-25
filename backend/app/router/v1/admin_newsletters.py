"""Administrator newsletters: write, test on yourself, send to the list."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from app.dependencies import NewsletterServiceDep, RequireAdmin
from app.models.newsletter_campaign import NewsletterCampaign
from app.schemas.newsletter import CampaignIn, CampaignOut, CampaignSendOut, CampaignTestOut

router = APIRouter(tags=["admin: newsletters"])


def _out(campaign: NewsletterCampaign, pending: int = 0, failed: int = 0) -> CampaignOut:
    out = CampaignOut.model_validate(campaign)
    out.pending, out.failed = pending, failed
    return out


@router.get("/newsletters", response_model=list[CampaignOut], summary="Newsletters, newest first")
async def list_newsletters(actor: RequireAdmin, service: NewsletterServiceDep) -> list[CampaignOut]:
    return [_out(c, p, f) for c, p, f in await service.list_with_progress()]


@router.post(
    "/newsletters",
    response_model=CampaignOut,
    status_code=status.HTTP_201_CREATED,
    summary="Save a new draft",
)
async def create_newsletter(
    payload: CampaignIn, actor: RequireAdmin, service: NewsletterServiceDep
) -> CampaignOut:
    return _out(await service.create(payload, actor=actor))


@router.get("/newsletters/{campaign_id}", response_model=CampaignOut, summary="One newsletter")
async def get_newsletter(
    campaign_id: uuid.UUID, actor: RequireAdmin, service: NewsletterServiceDep
) -> CampaignOut:
    return _out(*await service.get_with_progress(campaign_id))


@router.put("/newsletters/{campaign_id}", response_model=CampaignOut, summary="Edit a draft")
async def update_newsletter(
    campaign_id: uuid.UUID,
    payload: CampaignIn,
    actor: RequireAdmin,
    service: NewsletterServiceDep,
) -> CampaignOut:
    return _out(await service.update(campaign_id, payload, actor=actor))


@router.delete(
    "/newsletters/{campaign_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a draft"
)
async def delete_newsletter(
    campaign_id: uuid.UUID, actor: RequireAdmin, service: NewsletterServiceDep
) -> None:
    await service.delete(campaign_id, actor=actor)


@router.post(
    "/newsletters/{campaign_id}/test",
    response_model=CampaignTestOut,
    summary="Email this issue to yourself only",
)
async def test_newsletter(
    campaign_id: uuid.UUID, actor: RequireAdmin, service: NewsletterServiceDep
) -> CampaignTestOut:
    return CampaignTestOut(sent_to=await service.send_test(campaign_id, actor=actor))


@router.post(
    "/newsletters/{campaign_id}/send",
    response_model=CampaignSendOut,
    summary="Send this issue to everyone on the list",
)
async def send_newsletter(
    campaign_id: uuid.UUID, actor: RequireAdmin, service: NewsletterServiceDep
) -> CampaignSendOut:
    """One issue goes out once. Each email is its own queued job, so a restart resumes it."""
    return CampaignSendOut(queued=await service.send(campaign_id, actor=actor))
