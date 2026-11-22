from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import func, select

from app.core.pagination import PageParams
from app.models.lead import Enquiry, EnquiryStatus, NewsletterSubscriber
from app.repositories.base import BaseRepository


class EnquiryRepository(BaseRepository[Enquiry]):
    model = Enquiry

    async def page(
        self, params: PageParams, *, status: EnquiryStatus | None
    ) -> tuple[Sequence[Enquiry], int]:
        conditions = [Enquiry.status == status] if status is not None else []
        return await self.paginate(params, *conditions, order_by=[Enquiry.created_at.desc()])

    async def counts(self) -> dict[str, int]:
        rows = (
            await self.session.execute(
                select(Enquiry.status, func.count()).group_by(Enquiry.status)
            )
        ).all()
        return {str(r[0].value if hasattr(r[0], "value") else r[0]): int(r[1]) for r in rows}


class SubscriberRepository(BaseRepository[NewsletterSubscriber]):
    model = NewsletterSubscriber

    async def by_email(self, email: str) -> NewsletterSubscriber | None:
        return await self.find_one(NewsletterSubscriber.email == email.lower())

    async def by_token(self, token: str) -> NewsletterSubscriber | None:
        return await self.find_one(NewsletterSubscriber.unsubscribe_token == token)

    async def page(
        self, params: PageParams, *, search: str | None
    ) -> tuple[Sequence[NewsletterSubscriber], int]:
        conditions = []
        if search:
            conditions.append(NewsletterSubscriber.email.icontains(search.strip(), autoescape=True))
        return await self.paginate(
            params, *conditions, order_by=[NewsletterSubscriber.created_at.desc()]
        )

    async def active_emails(self, limit: int) -> Sequence[str]:
        statement = (
            select(NewsletterSubscriber.email)
            .where(NewsletterSubscriber.subscribed.is_(True))
            .order_by(NewsletterSubscriber.created_at)
            .limit(limit)
        )
        return (await self.session.execute(statement)).scalars().all()

    async def active_count(self) -> int:
        return await self.count(NewsletterSubscriber.subscribed.is_(True))
