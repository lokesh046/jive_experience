"""The refund policy: validated tiers, a site default with per-event override, and the quote."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.policy import CancellationPolicy
from app.services.refund import RefundService
from tests.integration.conftest import customer_session, seed_admin, sign_in_as
from tests.integration.google_stub import StubGoogleClient
from tests.integration.test_review_fixes import _confirmed_booking_with_tickets, make_event

pytestmark = pytest.mark.integration

DEFAULT = {"tiers": [{"hours_before": 168, "percent": 100}, {"hours_before": 48, "percent": 50}]}


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_policy_tiers_are_sorted_and_must_not_refund_more_when_later() -> None:
    policy = CancellationPolicy.model_validate(
        {"tiers": [{"hours_before": 48, "percent": 50}, {"hours_before": 168, "percent": 100}]}
    )
    assert [t.hours_before for t in policy.tiers] == [168, 48]
    with pytest.raises(ValidationError):
        CancellationPolicy.model_validate(
            {"tiers": [{"hours_before": 168, "percent": 20}, {"hours_before": 48, "percent": 80}]}
        )
    with pytest.raises(ValidationError):
        CancellationPolicy.model_validate(
            {"tiers": [{"hours_before": 48, "percent": 50}, {"hours_before": 48, "percent": 10}]}
        )
    with pytest.raises(ValidationError):
        CancellationPolicy.model_validate({"tiers": [{"hours_before": 24, "percent": 101}]})


async def test_admin_sets_the_default_policy_and_it_is_public_and_audited(
    api: AsyncClient, db_session: AsyncSession, google: StubGoogleClient
) -> None:
    admin = await sign_in_as(api, google, await seed_admin(db_session))
    put = await api.put(
        "/api/v1/admin/settings/cancellation-policy",
        headers=bearer(admin),
        json={"policy": DEFAULT},
    )
    assert put.status_code == 200, put.text
    assert [t["percent"] for t in put.json()["policy"]["tiers"]] == [100, 50]

    public = (await api.get("/api/v1/system/policy/cancellation")).json()
    assert public["policy"]["tiers"][0] == {"hours_before": 168, "percent": 100}

    audited = (
        await db_session.execute(
            sa.text(
                "SELECT count(*) FROM audit_logs "
                "WHERE action = 'settings.cancellation_policy_changed'"
            )
        )
    ).scalar_one()
    assert audited >= 1

    cleared = await api.put(
        "/api/v1/admin/settings/cancellation-policy", headers=bearer(admin), json={"policy": None}
    )
    assert cleared.json()["policy"] is None
    assert (await api.get("/api/v1/system/policy/cancellation")).json()["policy"] is None


async def test_only_an_admin_can_change_the_default_policy(
    api: AsyncClient, google: StubGoogleClient
) -> None:
    url = "/api/v1/admin/settings/cancellation-policy"
    assert (await api.put(url, json={"policy": DEFAULT})).status_code == 401
    customer = await customer_session(api, google)
    assert (
        await api.put(url, headers=bearer(customer["access"]), json={"policy": DEFAULT})
    ).status_code == 403
    assert (await api.get(url, headers=bearer(customer["access"]))).status_code == 403


async def test_an_event_without_a_policy_uses_the_default_and_its_own_policy_wins(
    api: AsyncClient, db_session: AsyncSession, google: StubGoogleClient
) -> None:
    from app.core.config import Settings
    from app.models.commerce import Booking
    from app.models.event import Event
    from app.services.outbox import OutboxService
    from app.services.payment_provider import UnconfiguredPaymentProvider

    admin = await sign_in_as(api, google, await seed_admin(db_session))
    await api.put(
        "/api/v1/admin/settings/cancellation-policy",
        headers=bearer(admin),
        json={"policy": DEFAULT},
    )

    # A booking 10 days before the event: the default gives a full refund.
    _, booking, event = await _confirmed_booking_with_tickets(db_session, quantity=1)
    event_id, booking_id, slug = event.id, booking.id, event.slug
    await db_session.execute(
        sa.text("UPDATE events SET starts_at = :s WHERE id = :i"),
        {"s": datetime.now(UTC) + timedelta(days=10), "i": event_id},
    )
    await db_session.commit()
    db_session.expire_all()

    shown = (await api.get(f"/api/v1/events/{slug}")).json()["cancellation_policy"]
    assert [t["percent"] for t in shown["tiers"]] == [100, 50]

    refunds = RefundService(
        db_session,
        Settings(environment="test", secret_key="t" * 64),
        UnconfiguredPaymentProvider(),
        OutboxService(db_session),
    )
    fresh_event = await db_session.get(Event, event_id)
    fresh_booking = await db_session.get(Booking, booking_id)
    assert fresh_event is not None and fresh_booking is not None
    full = await refunds.quote(booking=fresh_booking, event=fresh_event)
    assert full.eligible and full.percent == 100
    assert full.amount_paise == fresh_booking.total_paise

    # The event's own, stricter policy overrides the default.
    mine = (
        await api.patch(
            f"/api/v1/admin/events/{event_id}",
            headers=bearer(admin),
            json={"cancellation_policy": {"tiers": [{"hours_before": 480, "percent": 25}]}},
        )
    ).json()
    assert mine["cancellation_policy"]["tiers"] == [{"hours_before": 480, "percent": 25}]
    db_session.expire_all()
    fresh_event = await db_session.get(Event, event_id)
    fresh_booking = await db_session.get(Booking, booking_id)
    assert fresh_event is not None and fresh_booking is not None
    # 10 days is 240 hours, which is inside the 480-hour window: nothing to refund.
    late = await refunds.quote(booking=fresh_booking, event=fresh_event)
    assert not late.eligible

    # Clearing it sends the event back to the default.
    cleared = await api.patch(
        f"/api/v1/admin/events/{event_id}",
        headers=bearer(admin),
        json={"cancellation_policy": None},
    )
    assert cleared.json()["cancellation_policy"] is None


async def test_a_bad_policy_on_an_event_is_refused(
    api: AsyncClient, db_session: AsyncSession, google: StubGoogleClient
) -> None:
    event, _ = await make_event(db_session)
    await db_session.commit()
    admin = await sign_in_as(api, google, await seed_admin(db_session))
    url = f"/api/v1/admin/events/{event.id}"
    bad = {
        "cancellation_policy": {
            "tiers": [{"hours_before": 100, "percent": 10}, {"hours_before": 10, "percent": 90}]
        }
    }
    assert (await api.patch(url, headers=bearer(admin), json=bad)).status_code == 422
