"""Public forms: private-booking enquiries and the newsletter."""

from __future__ import annotations

from fastapi import APIRouter, status

from app.dependencies import FormRateLimit, LeadServiceDep, WaitlistServiceDep
from app.schemas.leads import EnquiryCreate, Received, SubscribeRequest, UnsubscribeRequest
from app.schemas.waitlist import WaitlistJoin, WaitlistLeave

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


@router.post(
    "/events/{slug}/waitlist",
    response_model=Received,
    status_code=status.HTTP_201_CREATED,
    dependencies=[FormRateLimit],
    summary="Join the waitlist for a sold-out event",
)
async def join_waitlist(slug: str, payload: WaitlistJoin, service: WaitlistServiceDep) -> Received:
    """Only while the tickets are gone: if they are available, the answer says so."""
    await service.join(slug, payload)
    return Received()


@router.post(
    "/waitlist/leave",
    response_model=Received,
    dependencies=[FormRateLimit],
    summary="Leave a waitlist, using the link in an email",
)
async def leave_waitlist(payload: WaitlistLeave, service: WaitlistServiceDep) -> Received:
    await service.leave(payload.token)
    return Received()
