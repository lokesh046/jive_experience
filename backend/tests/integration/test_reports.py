"""The admin sales report: the numbers must reconcile, and only admins may read them."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.commerce import Booking, BookingItem, BookingStatus
from app.models.fulfilment import Ticket, TicketStatus
from tests.integration.conftest import customer_session, seed_admin, sign_in_as
from tests.integration.google_stub import StubGoogleClient
from tests.integration.test_review_fixes import _confirmed_booking_with_tickets, make_event

pytestmark = pytest.mark.integration


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_sales_report_reconciles_sales_refunds_checkins_and_categories(
    api: AsyncClient, db_session: AsyncSession, google: StubGoogleClient
) -> None:
    # Two bookings for one event: 2 tickets (kept) and 1 ticket (later refunded in full).
    _, kept, event = await _confirmed_booking_with_tickets(db_session, quantity=2)
    event_id = event.id
    _, refunded, _ = await _confirmed_booking_with_tickets(db_session, quantity=1)
    await db_session.execute(
        sa.update(Booking).where(Booking.id == refunded.id).values(event_id=event_id)
    )
    await db_session.execute(
        sa.update(BookingItem)
        .where(BookingItem.booking_id == refunded.id)
        .values(
            ticket_category_id=sa.select(BookingItem.ticket_category_id)
            .where(BookingItem.booking_id == kept.id)
            .limit(1)
            .scalar_subquery()
        )
    )
    await db_session.execute(
        sa.update(Booking)
        .where(Booking.id == refunded.id)
        .values(status=BookingStatus.REFUNDED, refunded_paise=100000)
    )
    # One of the kept tickets is scanned at the gate.
    first_ticket = (
        await db_session.execute(sa.select(Ticket.id).where(Ticket.booking_id == kept.id).limit(1))
    ).scalar_one()
    await db_session.execute(
        sa.update(Ticket)
        .where(Ticket.id == first_ticket)
        .values(status=TicketStatus.CHECKED_IN, checked_in_at=datetime.now(UTC))
    )
    await db_session.commit()

    admin = await sign_in_as(api, google, await seed_admin(db_session))
    response = await api.get(
        "/api/v1/admin/reports/sales",
        params={"event_id": str(event_id), "days": 7},
        headers=bearer(admin),
    )
    assert response.status_code == 200, response.text
    report = response.json()

    s = report["summary"]
    assert s["gross_paise"] == 300000  # 2 x 1000 + 1 x 1000 rupees, all captured
    assert s["refunded_paise"] == 100000
    assert s["net_paise"] == 200000  # gross minus refunds
    assert s["tickets_sold"] == 2  # the refunded booking's ticket is not sold
    assert s["bookings"] == 1 and s["cancelled_bookings"] == 1
    assert s["checked_in"] == 1
    assert [e["event_id"] for e in report["events"]] == [str(event_id)]

    assert len(report["daily"]) == 7
    today = report["daily"][-1]
    assert today["gross_paise"] == 300000 and today["tickets"] == 3

    (category,) = [c for c in report["categories"] if c["tickets_sold"]]
    assert category["tickets_sold"] == 2 and category["gross_paise"] == 200000


async def test_a_draft_event_and_an_event_with_no_sales_report_zeros(
    api: AsyncClient, db_session: AsyncSession, google: StubGoogleClient
) -> None:
    event, _ = await make_event(db_session)
    await db_session.commit()
    admin = await sign_in_as(api, google, await seed_admin(db_session))
    report = (
        await api.get(
            "/api/v1/admin/reports/sales", params={"event_id": str(event.id)}, headers=bearer(admin)
        )
    ).json()
    assert report["summary"]["gross_paise"] == 0 and report["summary"]["tickets_sold"] == 0
    assert len(report["daily"]) == 30 and all(d["tickets"] == 0 for d in report["daily"])
    assert report["categories"][0]["tickets_sold"] == 0


async def test_only_admins_read_sales_and_the_range_is_limited(
    api: AsyncClient, db_session: AsyncSession, google: StubGoogleClient
) -> None:
    url = "/api/v1/admin/reports/sales"
    assert (await api.get(url)).status_code == 401
    customer = await customer_session(api, google)
    assert (await api.get(url, headers=bearer(customer["access"]))).status_code == 403
    admin = await sign_in_as(api, google, await seed_admin(db_session))
    assert (await api.get(url, params={"days": 3}, headers=bearer(admin))).status_code == 422
    assert (await api.get(url, params={"days": 400}, headers=bearer(admin))).status_code == 422
