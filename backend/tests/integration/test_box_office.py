"""Counter sales: cash and online, who may sell, and the per-seller totals."""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models.commerce import Booking
from app.services.booking import BookingService
from app.services.inventory import InventoryService
from app.services.outbox import OutboxService
from app.services.payment import PaymentService
from app.services.payment_provider import (
    ProviderPaymentState,
    UnconfiguredPaymentProvider,
    VerifiedPayment,
)
from app.services.refund import RefundService
from tests.integration.conftest import customer_session, seed_admin, seed_staff, sign_in_as
from tests.integration.google_stub import StubGoogleClient
from tests.integration.test_review_fixes import make_event

pytestmark = pytest.mark.integration


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def assign(db: AsyncSession, staff_id: uuid.UUID, event_id: uuid.UUID) -> None:
    await db.execute(
        sa.text("INSERT INTO staff_event_assignments (user_id, event_id) VALUES (:u, :e)"),
        {"u": staff_id, "e": event_id},
    )
    await db.commit()


async def test_a_cash_sale_without_an_email_is_confirmed_and_queues_the_tickets(
    api: AsyncClient, db_session: AsyncSession, google: StubGoogleClient
) -> None:
    event, category = await make_event(db_session, capacity=5)
    event_id, category_id = event.id, category.id
    await db_session.commit()
    admin = await sign_in_as(api, google, await seed_admin(db_session))

    response = await api.post(
        f"/api/v1/box-office/events/{event_id}/sales",
        headers=bearer(admin),
        json={
            "ticket_category_id": str(category_id),
            "quantity": 2,
            "method": "CASH",
            "buyer_name": "Ravi",
            "buyer_phone": "98765 43210",
        },
    )
    assert response.status_code == 201, response.text
    booking = response.json()
    assert booking["status"] == "CONFIRMED" and booking["source"] == "CASH"
    assert booking["total_paise"] == 200000

    row = (
        await db_session.execute(
            sa.text(
                "SELECT u.email, b.customer_note, b.issued_by_id IS NOT NULL "
                "FROM bookings b JOIN users u ON u.id = b.user_id WHERE b.reference = :r"
            ),
            {"r": booking["reference"]},
        )
    ).one()
    assert row[0].endswith("@walk-in.invalid")
    assert "Ravi" in row[1] and "98765 43210" in row[1]
    assert row[2] is True

    detail = await api.get(
        f"/api/v1/box-office/bookings/{booking['reference']}", headers=bearer(admin)
    )
    assert (
        detail.status_code == 200 and detail.json()["booking"]["reference"] == booking["reference"]
    )


async def test_an_online_sale_holds_the_seats_and_is_not_paid_until_the_gateway_says_so(
    api: AsyncClient, db_session: AsyncSession, google: StubGoogleClient
) -> None:
    event, category = await make_event(db_session, capacity=5)
    event_id, category_id = event.id, category.id
    await db_session.commit()
    admin_user = await seed_admin(db_session)
    admin = await sign_in_as(api, google, admin_user)

    response = await api.post(
        f"/api/v1/box-office/events/{event_id}/sales",
        headers=bearer(admin),
        json={"ticket_category_id": str(category_id), "quantity": 1, "method": "ONLINE"},
    )
    assert response.status_code == 201, response.text
    booking = response.json()
    assert booking["status"] == "PENDING" and booking["source"] == "ONLINE"
    held = (
        await db_session.execute(
            sa.text("SELECT reserved_count, sold_count FROM ticket_categories WHERE id = :i"),
            {"i": category_id},
        )
    ).one()
    assert tuple(held) == (1, 0)

    # The seller asked for tickets before any payment: none are shown.
    pending = await api.get(
        f"/api/v1/box-office/bookings/{booking['reference']}", headers=bearer(admin)
    )
    assert pending.json()["tickets"] == []

    # A verified payment from the gateway is what confirms it.
    stored = (
        await db_session.execute(
            sa.text("SELECT id FROM bookings WHERE reference = :r"), {"r": booking["reference"]}
        )
    ).scalar_one()
    settings = Settings(environment="test", secret_key="t" * 64)
    outbox = OutboxService(db_session)
    inventory = InventoryService(db_session, settings.reservation_hold_seconds)
    bookings = BookingService(db_session, settings, inventory, outbox)
    refunds = RefundService(db_session, settings, UnconfiguredPaymentProvider(), outbox)
    payments = PaymentService(
        db_session, settings, UnconfiguredPaymentProvider(), bookings, refunds
    )
    order_id, payment_id = f"order_{uuid.uuid4().hex[:10]}", f"pay_{uuid.uuid4().hex[:10]}"
    await db_session.execute(
        sa.text(
            "INSERT INTO payments (booking_id, provider, provider_order_id, amount_paise, "
            "currency, idempotency_key, status) VALUES (:b, 'unconfigured', :o, 100000, "
            "'INR', :k, 'PENDING')"
        ),
        {"b": stored, "o": order_id, "k": f"order:{stored}"},
    )
    await db_session.commit()
    await payments.confirm_from_provider(
        VerifiedPayment(
            provider_payment_id=payment_id,
            provider_order_id=order_id,
            amount_paise=100000,
            currency="INR",
            state=ProviderPaymentState.SUCCEEDED,
            provider_status="captured",
        ),
        source="test",
    )
    db_session.expire_all()
    status = (
        await db_session.execute(sa.select(Booking.status).where(Booking.id == stored))
    ).scalar_one()
    assert status.value == "CONFIRMED"

    totals = await api.get(f"/api/v1/box-office/events/{event_id}/summary", headers=bearer(admin))
    rows = totals.json()
    assert len(rows) == 1 and rows[0]["online_tickets"] == 1 and rows[0]["online_paise"] == 100000
    assert rows[0]["cash_tickets"] == 0


async def test_only_assigned_staff_may_sell_and_each_sees_only_their_own_sales(
    api: AsyncClient, db_session: AsyncSession, google: StubGoogleClient
) -> None:
    event, category = await make_event(db_session, capacity=9)
    event_id, category_id = event.id, category.id
    one, two = await seed_staff(db_session), await seed_staff(db_session)
    one_id = one.id
    await db_session.commit()
    token_one = await sign_in_as(api, google, one)
    token_two = await sign_in_as(api, google, two)
    sale = {"ticket_category_id": str(category_id), "quantity": 1, "method": "CASH"}
    url = f"/api/v1/box-office/events/{event_id}/sales"

    # Not assigned: refused.
    assert (await api.post(url, headers=bearer(token_one), json=sale)).status_code == 403
    await assign(db_session, one_id, event_id)
    made = await api.post(url, headers=bearer(token_one), json=sale)
    assert made.status_code == 201, made.text
    reference = made.json()["reference"]

    # Another seller cannot open it, even when assigned to the same event.
    await assign(db_session, two.id, event_id)
    assert (
        await api.get(f"/api/v1/box-office/bookings/{reference}", headers=bearer(token_two))
    ).status_code == 404
    mine = await api.get(f"/api/v1/box-office/events/{event_id}/summary", headers=bearer(token_one))
    theirs = await api.get(
        f"/api/v1/box-office/events/{event_id}/summary", headers=bearer(token_two)
    )
    assert mine.json()[0]["cash_tickets"] == 1 and theirs.json() == []


async def test_customers_and_visitors_cannot_use_the_box_office(
    api: AsyncClient, db_session: AsyncSession, google: StubGoogleClient
) -> None:
    event, category = await make_event(db_session)
    event_id, category_id = event.id, category.id
    await db_session.commit()
    url = f"/api/v1/box-office/events/{event_id}/sales"
    sale = {"ticket_category_id": str(category_id), "quantity": 1, "method": "CASH"}
    assert (await api.post(url, json=sale)).status_code == 401
    customer = await customer_session(api, google)
    assert (await api.post(url, headers=bearer(customer["access"]), json=sale)).status_code == 403
    admin = await sign_in_as(api, google, await seed_admin(db_session))
    comp = await api.post(url, headers=bearer(admin), json={**sale, "method": "COMPLIMENTARY"})
    assert comp.status_code == 422


async def test_mail_to_a_walk_in_address_is_skipped() -> None:
    from app.core.mailer import Mail, send_mail

    settings = Settings(environment="test", secret_key="t" * 64)
    await send_mail(settings, Mail(to="walkin-x@walk-in.invalid", subject="s", text="t", html="h"))
