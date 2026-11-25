"""Newsletters: write one, test it on yourself, send it to the list.

Sending queues one message per subscriber in the outbox, in the same transaction that marks the
issue as sent, so a restart resumes rather than repeats, and a double click sends one issue.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import mailer
from app.core.config import Settings
from app.core.errors import BusinessRuleError, NotFoundError, ServiceUnavailableError
from app.models.newsletter_campaign import CampaignStatus, NewsletterCampaign
from app.models.user import User
from app.repositories.catalogue import EventRepository
from app.repositories.newsletter import TOPIC, CampaignRepository
from app.schemas.newsletter import CampaignIn
from app.services.audit import AuditService
from app.services.newsletter_mail import build_campaign_mail
from app.services.outbox import OutboxService

logger = structlog.get_logger(__name__)


class NewsletterService:
    def __init__(self, session: AsyncSession, settings: Settings, outbox: OutboxService) -> None:
        self.session = session
        self.settings = settings
        self.outbox = outbox
        self.campaigns = CampaignRepository(session)
        self.events = EventRepository(session)
        self.audit = AuditService(session)

    async def list_with_progress(self) -> list[tuple[NewsletterCampaign, int, int]]:
        rows = list(await self.campaigns.newest())
        progress = await self.campaigns.progress([c.id for c in rows])
        return [(c, *progress.get(c.id, (0, 0))) for c in rows]

    async def get_with_progress(
        self, campaign_id: uuid.UUID
    ) -> tuple[NewsletterCampaign, int, int]:
        campaign = await self._get(campaign_id)
        progress = await self.campaigns.progress([campaign.id])
        return (campaign, *progress.get(campaign.id, (0, 0)))

    async def create(self, payload: CampaignIn, *, actor: User) -> NewsletterCampaign:
        await self._check_event(payload)
        campaign = NewsletterCampaign(**payload.model_dump(), created_by_id=actor.id)
        self.campaigns.add(campaign)
        await self.session.flush()
        await self.audit.record(
            "newsletter.created",
            entity_type="newsletter_campaign",
            entity_id=campaign.id,
            actor=actor,
            after={"subject": campaign.subject},
        )
        await self.session.commit()
        return campaign

    async def update(
        self, campaign_id: uuid.UUID, payload: CampaignIn, *, actor: User
    ) -> NewsletterCampaign:
        campaign = await self._draft(campaign_id)
        await self._check_event(payload)
        for field, value in payload.model_dump().items():
            setattr(campaign, field, value)
        await self.audit.record(
            "newsletter.updated",
            entity_type="newsletter_campaign",
            entity_id=campaign.id,
            actor=actor,
        )
        await self.session.commit()
        return campaign

    async def delete(self, campaign_id: uuid.UUID, *, actor: User) -> None:
        campaign = await self._draft(campaign_id)
        await self.audit.record(
            "newsletter.deleted",
            entity_type="newsletter_campaign",
            entity_id=campaign.id,
            actor=actor,
            before={"subject": campaign.subject},
        )
        await self.campaigns.delete(campaign)
        await self.session.commit()

    async def send_test(self, campaign_id: uuid.UUID, *, actor: User) -> str:
        """The real email, to the administrator only, so they see exactly what people will."""
        self._require_email()
        campaign = await self._get(campaign_id)
        event = await self.events.get(campaign.event_id) if campaign.event_id else None
        mail = build_campaign_mail(
            self.settings, campaign, event, to=actor.email, unsubscribe_url=None, test=True
        )
        await mailer.send_mail(self.settings, mail)
        return actor.email

    async def send(self, campaign_id: uuid.UUID, *, actor: User) -> int:
        """Queue the issue to every current subscriber. Returns how many."""
        self._require_email()
        campaign = await self._draft(campaign_id)
        subscribers: Sequence[tuple[uuid.UUID, str]] = await self.campaigns.active_subscribers()
        if not subscribers:
            raise BusinessRuleError("There is nobody subscribed yet.", code="NO_SUBSCRIBERS")
        if not await self.campaigns.mark_sent(campaign.id, recipients=len(subscribers)):
            raise BusinessRuleError("This issue was already sent.", code="CAMPAIGN_ALREADY_SENT")
        for subscriber_id, _email in subscribers:
            await self.outbox.enqueue(
                topic=TOPIC,
                payload={"campaign_id": str(campaign.id), "subscriber_id": str(subscriber_id)},
                dedup_key=f"{TOPIC}:{campaign.id}:{subscriber_id}",
            )
        await self.audit.record(
            "newsletter.sent",
            entity_type="newsletter_campaign",
            entity_id=campaign.id,
            actor=actor,
            after={"subject": campaign.subject, "recipients": len(subscribers)},
        )
        await self.session.commit()
        logger.info("newsletter_queued", campaign_id=str(campaign.id), recipients=len(subscribers))
        return len(subscribers)

    # ----------------------------------------------------------------- helpers ---

    def _require_email(self) -> None:
        if not self.settings.email_configured:
            raise ServiceUnavailableError(
                "Email is not set up, so nothing can be sent.", code="EMAIL_NOT_CONFIGURED"
            )

    async def _check_event(self, payload: CampaignIn) -> None:
        if payload.event_id is not None and await self.events.get(payload.event_id) is None:
            raise NotFoundError("That event no longer exists.", code="EVENT_NOT_FOUND")

    async def _get(self, campaign_id: uuid.UUID) -> NewsletterCampaign:
        campaign = await self.campaigns.get(campaign_id)
        if campaign is None:
            raise NotFoundError("Newsletter not found.", code="NEWSLETTER_NOT_FOUND")
        return campaign

    async def _draft(self, campaign_id: uuid.UUID) -> NewsletterCampaign:
        campaign = await self._get(campaign_id)
        if campaign.status != CampaignStatus.DRAFT.value:
            raise BusinessRuleError(
                "This issue has been sent, so it can no longer be changed.",
                code="CAMPAIGN_ALREADY_SENT",
            )
        return campaign
