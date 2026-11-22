"""Enquiries and newsletter signups: what the public forms do, and what admins do with them."""

from __future__ import annotations

import csv
import io
import secrets
import uuid
from collections.abc import Sequence

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.core.pagination import PageParams
from app.models.lead import Enquiry, EnquiryStatus, NewsletterSubscriber
from app.models.user import User
from app.repositories.lead import EnquiryRepository, SubscriberRepository
from app.schemas.leads import EnquiryCreate, EnquiryUpdate
from app.services.audit import AuditService
from app.services.outbox import TOPIC_ENQUIRY_RECEIVED, TOPIC_NEWSLETTER_SUBSCRIBED, OutboxService

logger = structlog.get_logger(__name__)

MAX_EXPORT_ROWS = 100_000


def _safe(value: str) -> str:
    """Spreadsheets run cells that start with = + - @ as formulas; defuse them."""
    return "'" + value if value[:1] in ("=", "+", "-", "@", "\t", "\r") else value


class LeadService:
    def __init__(self, session: AsyncSession, outbox: OutboxService) -> None:
        self.session = session
        self.outbox = outbox
        self.enquiries = EnquiryRepository(session)
        self.subscribers = SubscriberRepository(session)
        self.audit = AuditService(session)

    # ------------------------------------------------------------ public ---

    async def submit_enquiry(self, payload: EnquiryCreate) -> None:
        if payload.website:
            logger.info("enquiry_honeypot_tripped")
            return
        enquiry = Enquiry(
            name=payload.name,
            email=str(payload.email).lower(),
            phone=payload.phone,
            event_date=payload.event_date,
            guests=payload.guests,
            message=payload.message,
        )
        self.enquiries.add(enquiry)
        await self.session.flush()
        await self.outbox.enqueue(
            topic=TOPIC_ENQUIRY_RECEIVED,
            payload={"enquiry_id": str(enquiry.id)},
            dedup_key=f"enquiry.received:{enquiry.id}",
        )
        await self.session.commit()

    async def subscribe(self, email: str, *, website: str = "") -> None:
        """Add an address to the list. Always looks the same to the caller."""
        if website:
            logger.info("newsletter_honeypot_tripped")
            return
        email = email.lower()
        existing = await self.subscribers.by_email(email)
        if existing is None:
            row = NewsletterSubscriber(
                email=email, subscribed=True, unsubscribe_token=secrets.token_urlsafe(32)
            )
            self.subscribers.add(row)
            await self.session.flush()
        elif not existing.subscribed:
            existing.subscribed = True
            existing.unsubscribed_at = None
            row = existing
        else:
            return  # already on the list: say nothing, send nothing
        await self.outbox.enqueue(
            topic=TOPIC_NEWSLETTER_SUBSCRIBED,
            payload={"subscriber_id": str(row.id)},
            dedup_key=f"newsletter.subscribed:{row.id}:{row.updated_at or row.created_at}",
        )
        await self.session.commit()

    async def unsubscribe(self, token: str) -> None:
        from app.models.base import utc_now

        row = await self.subscribers.by_token(token)
        if row is not None and row.subscribed:
            row.subscribed = False
            row.unsubscribed_at = utc_now()
            await self.session.commit()

    # ------------------------------------------------------------- admin ---

    async def list_enquiries(
        self, params: PageParams, *, status: EnquiryStatus | None
    ) -> tuple[Sequence[Enquiry], int, dict[str, int]]:
        rows, total = await self.enquiries.page(params, status=status)
        return rows, total, await self.enquiries.counts()

    async def update_enquiry(
        self, enquiry_id: uuid.UUID, payload: EnquiryUpdate, *, actor: User
    ) -> Enquiry:
        enquiry = await self.enquiries.get(enquiry_id)
        if enquiry is None:
            raise NotFoundError("Enquiry not found.", code="ENQUIRY_NOT_FOUND")
        before = {"status": enquiry.status.value}
        updates = payload.model_dump(exclude_unset=True)
        for field, value in updates.items():
            setattr(enquiry, field, value)
        enquiry.handled_by_id = actor.id
        await self.audit.record(
            "enquiry.updated",
            entity_type="enquiry",
            entity_id=enquiry.id,
            actor=actor,
            before=before,
            after={"status": enquiry.status.value},
        )
        await self.session.commit()
        return enquiry

    async def list_subscribers(
        self, params: PageParams, *, search: str | None
    ) -> tuple[Sequence[NewsletterSubscriber], int, int]:
        rows, total = await self.subscribers.page(params, search=search)
        return rows, total, await self.subscribers.active_count()

    async def subscribers_csv(self, *, actor: User) -> bytes:
        """The addresses people are subscribed with. Audited: it is a list of personal data."""
        emails = await self.subscribers.active_emails(MAX_EXPORT_ROWS)
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(["Email"])
        for email in emails:
            writer.writerow([_safe(email)])
        await self.audit.record(
            "newsletter.subscribers_exported",
            entity_type="newsletter",
            actor=actor,
            after={"rows": len(emails)},
        )
        await self.session.commit()
        return b"\xef\xbb\xbf" + out.getvalue().encode()
