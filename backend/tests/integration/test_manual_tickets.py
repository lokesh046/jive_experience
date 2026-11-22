"""Complimentary and cash tickets: real capacity, no gateway, admin-only."""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models.commerce import Booking
from app.models.event import Event
from app.services.outbox import OutboxService
from app.services.payment_provider import UnconfiguredPaymentProvider
from app.services.refund import RefundService
from tests.integration.conftest import customer_session, seed_admin, sign_in_as, unique_email
from tests.integration.google_stub import StubGoogleClient
from tests.integration.test_review_fixes import make_event

pytestmark = pytest.mark.integration


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_a_complimentary_ticket_takes_capacity_costs_nothing_and_queues_the_tickets(
    api: AsyncClient, db_session: AsyncSession, google: StubGoogleClient
) -> None:
    event, category = await make_event(db_session, capacity=5)
    event_id, category_id = event.id, category.id
    await db_session.commit()
    admin = await sign_in_as(api, google, await seed_admin(db_session))
    email = unique_email("guest")

    response = await api.post(
        f"/api/v1/admin/events/{event_id}/manual-tickets",
        headers=bearer(admin),
        json={
            "kind": "COMPLIMENTARY",
            "email": email.upper(),
            "full_name": "  Meera Rao  ",
            "ticket_category_id": str(category_id),
            "quantity": 2,
            "note": "Artist guest",
        },
    )
    assert response.status_code == 201, response.text
    booking = response.json()
    assert booking["source"] == "COMPLIMENTARY" and booking["status"] == "CONFIRMED"
    assert booking["total_paise"] == 0 and booking["quantity"] == 2
    assert booking["items"][0]["unit_price_paise"] == 0

    # Capacity is really used, the person has an account, and the worker will issue the QR tickets.
    sold = (
        await db_session.execute(
            sa.text("SELECT sold_count, reserved_count FROM ticket_categories WHERE id = :i"),
            {"i": category_id},
        )
    ).one()
    assert tuple(sold) == (2, 0)
    user = (
        await db_session.execute(
            sa.text("SELECT role, full_name, google_sub FROM users WHERE email = :e"),
            {"e": email.lower()},
        )
    ).one()
    assert (user[0], user[1], user[2]) == ("CUSTOMER", "Meera Rao", None)
    queued = (
        await db_session.execute(
            sa.text(
                "SELECT count(*) FROM outbox_messages WHERE topic = 'booking.confirmed' "
                "AND dedup_key = :k"
            ),
            {"k": f"booking.confirmed:{booking['id']}"},
        )
    ).scalar_one()
    assert queued == 1
    audited = (
        await db_session.execute(
            sa.text("SELECT count(*) FROM audit_logs WHERE action = 'booking.issued_manually'")
        )
    ).scalar_one()
    assert audited >= 1


async def test_a_cash_ticket_records_the_price_as_revenue(
    api: AsyncClient, db_session: AsyncSession, google: StubGoogleClient
) -> None:
    event, category = await make_event(db_session)
    event_id, category_id = event.id, category.id
    await db_session.commit()
    admin = await sign_in_as(api, google, await seed_admin(db_session))
    booking = (
        await api.post(
            f"/api/v1/admin/events/{event_id}/manual-tickets",
            headers=bearer(admin),
            json={
                "kind": "CASH",
                "email": unique_email("door"),
                "full_name": "Door Buyer",
                "ticket_category_id": str(category_id),
                "quantity": 3,
            },
        )
    ).json()
    assert booking["source"] == "CASH" and booking["total_paise"] == 300000  # 3 x 1,000 rupees
    report = (
        await api.get(
            "/api/v1/admin/reports/sales", params={"event_id": str(event_id)}, headers=bearer(admin)
        )
    ).json()
    assert report["summary"]["gross_paise"] == 300000 and report["summary"]["tickets_sold"] == 3


async def test_capacity_is_never_exceeded_and_an_existing_account_is_reused(
    api: AsyncClient, db_session: AsyncSession, google: StubGoogleClient
) -> None:
    event, category = await make_event(db_session, capacity=2)
    event_id, category_id = event.id, category.id
    await db_session.commit()
    admin = await sign_in_as(api, google, await seed_admin(db_session))
    url = f"/api/v1/admin/events/{event_id}/manual-tickets"
    body = {
        "kind": "COMPLIMENTARY",
        "email": unique_email("same"),
        "full_name": "Same Person",
        "ticket_category_id": str(category_id),
        "quantity": 2,
    }
    assert (await api.post(url, headers=bearer(admin), json=body)).status_code == 201
    full = await api.post(url, headers=bearer(admin), json={**body, "quantity": 1})
    assert full.status_code == 409 and full.json()["error"]["code"] == "INSUFFICIENT_INVENTORY"
    sold = (
        await db_session.execute(
            sa.text("SELECT sold_count FROM ticket_categories WHERE id = :i"), {"i": category_id}
        )
    ).scalar_one()
    assert sold == 2
    people = (
        await db_session.execute(
            sa.text("SELECT count(*) FROM users WHERE email = :e"), {"e": body["email"].lower()}
        )
    ).scalar_one()
    assert people == 1


async def test_manual_tickets_are_refused_for_bad_input_and_non_admins(
    api: AsyncClient, db_session: AsyncSession, google: StubGoogleClient
) -> None:
    event, category = await make_event(db_session)
    event_id, category_id = event.id, category.id
    await db_session.execute(
        sa.text("UPDATE events SET status = 'DRAFT' WHERE id = :i"), {"i": event_id}
    )
    await db_session.commit()
    db_session.expire_all()
    url = f"/api/v1/admin/events/{event_id}/manual-tickets"
    good = {
        "kind": "COMPLIMENTARY",
        "email": unique_email("x"),
        "full_name": "X",
        "ticket_category_id": str(category_id),
    }

    assert (await api.post(url, json=good)).status_code == 401
    customer = await customer_session(api, google)
    assert (await api.post(url, headers=bearer(customer["access"]), json=good)).status_code == 403

    admin = await sign_in_as(api, google, await seed_admin(db_session))
    draft = await api.post(url, headers=bearer(admin), json=good)
    assert draft.status_code == 422 and draft.json()["error"]["code"] == "EVENT_NOT_SELLABLE"
    await db_session.execute(
        sa.text("UPDATE events SET status = 'PUBLISHED' WHERE id = :i"), {"i": event_id}
    )
    await db_session.commit()
    db_session.expire_all()
    for bad in (
        {**good, "kind": "ONLINE"},
        {**good, "email": "not-an-email"},
        {**good, "quantity": 0},
        {**good, "ticket_category_id": "00000000-0000-0000-0000-000000000000"},
    ):
        assert (await api.post(url, headers=bearer(admin), json=bad)).status_code in (404, 422)


async def test_a_hand_issued_booking_cannot_be_self_cancelled_for_a_refund(
    api: AsyncClient, db_session: AsyncSession, google: StubGoogleClient
) -> None:
    event, category = await make_event(db_session)
    event_id, category_id = event.id, category.id
    await db_session.commit()
    admin = await sign_in_as(api, google, await seed_admin(db_session))
    booking = (
        await api.post(
            f"/api/v1/admin/events/{event_id}/manual-tickets",
            headers=bearer(admin),
            json={
                "kind": "CASH",
                "email": unique_email("cashier"),
                "full_name": "Cash Buyer",
                "ticket_category_id": str(category_id),
            },
        )
    ).json()
    refunds = RefundService(
        db_session,
        Settings(environment="test", secret_key="t" * 64),
        UnconfiguredPaymentProvider(),
        OutboxService(db_session),
    )
    stored = await db_session.get(Booking, booking["id"])
    stored_event = await db_session.get(Event, event_id)
    assert stored is not None and stored_event is not None
    quote = await refunds.quote(booking=stored, event=stored_event)
    assert quote.eligible is False and "issued by us" in quote.reason
