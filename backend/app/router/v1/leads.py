"""Public forms: private-booking enquiries and the newsletter."""

from __future__ import annotations

from fastapi import APIRouter, status

from app.dependencies import FormRateLimit, LeadServiceDep
from app.schemas.leads import EnquiryCreate, Received, SubscribeRequest, UnsubscribeRequest

router = APIRouter(tags=["public forms"])


@router.post(
    "/enquiries",
    response_model=Received,
    status_code=status.HTTP_201_CREATED,
    dependencies=[FormRateLimit],
    summary="Send a private-booking enquiry",
)
async def send_enquiry(payload: EnquiryCreate, service: LeadServiceDep) -> Received:
    await service.submit_enquiry(payload)
    return Received()


@router.post(
    "/newsletter/subscribe",
    response_model=Received,
    dependencies=[FormRateLimit],
    summary="Join the newsletter",
)
async def subscribe(payload: SubscribeRequest, service: LeadServiceDep) -> Received:
    """Looks the same whether or not the address was already on the list."""
    await service.subscribe(str(payload.email), website=payload.website)
    return Received()


@router.post(
    "/newsletter/unsubscribe",
    response_model=Received,
    dependencies=[FormRateLimit],
    summary="Leave the newsletter, using the link in an email",
)
async def unsubscribe(payload: UnsubscribeRequest, service: LeadServiceDep) -> Received:
    await service.unsubscribe(payload.token)
    return Received()
