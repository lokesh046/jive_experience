"""The event lineup: admin sets it as one ordered list, the public page shows it."""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.conftest import customer_session, seed_admin, sign_in_as
from tests.integration.google_stub import StubGoogleClient
from tests.integration.test_review_fixes import make_event

pytestmark = pytest.mark.integration


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_lineup_is_set_in_order_and_shown_publicly(
    api: AsyncClient, db_session: AsyncSession, google: StubGoogleClient
) -> None:
    event, _ = await make_event(db_session)
    await db_session.commit()
    admin = await sign_in_as(api, google, await seed_admin(db_session))

    # An event with no lineup says so with an empty list, not a missing field.
    before = await api.get(f"/api/v1/events/{event.slug}")
    assert before.status_code == 200 and before.json()["lineup"] == []

    put = await api.put(
        f"/api/v1/admin/events/{event.id}/lineup",
        headers=bearer(admin),
        json={
            "performers": [
                {"name": "  Kohra  ", "role": "Deep soundscapes", "performs_at": None},
                {
                    "name": "Anyasa",
                    "role": "Modular synths",
                    "photo_url": "https://res.cloudinary.com/demo/image/upload/a.jpg",
                    "performs_at": "2027-01-10T15:30:00+00:00",
                },
            ]
        },
    )
    assert put.status_code == 200, put.text
    assert [p["name"] for p in put.json()] == ["Kohra", "Anyasa"]

    # The public page reflects it at once, in the same order.
    shown = (await api.get(f"/api/v1/events/{event.slug}")).json()["lineup"]
    assert [p["name"] for p in shown] == ["Kohra", "Anyasa"]
    assert shown[1]["performs_at"].startswith("2027-01-10T15:30")
    assert shown[0]["photo_url"] is None

    # Saving again replaces the list rather than adding to it.
    again = await api.put(
        f"/api/v1/admin/events/{event.id}/lineup",
        headers=bearer(admin),
        json={"performers": [{"name": "Blot!"}]},
    )
    assert [p["name"] for p in again.json()] == ["Blot!"]
    assert [
        p["name"] for p in (await api.get(f"/api/v1/events/{event.slug}")).json()["lineup"]
    ] == ["Blot!"]

    # The admin view of the event carries it too, so the editor can load it.
    detail = await api.get(f"/api/v1/admin/events/{event.id}", headers=bearer(admin))
    assert [p["name"] for p in detail.json()["performers"]] == ["Blot!"]

    cleared = await api.put(
        f"/api/v1/admin/events/{event.id}/lineup", headers=bearer(admin), json={"performers": []}
    )
    assert cleared.status_code == 200 and cleared.json() == []


async def test_only_an_admin_can_set_the_lineup(
    api: AsyncClient, db_session: AsyncSession, google: StubGoogleClient
) -> None:
    event, _ = await make_event(db_session)
    await db_session.commit()
    url = f"/api/v1/admin/events/{event.id}/lineup"
    body = {"performers": [{"name": "Someone"}]}

    assert (await api.put(url, json=body)).status_code == 401
    customer = await customer_session(api, google)
    assert (await api.put(url, headers=bearer(customer["access"]), json=body)).status_code == 403


async def test_lineup_input_is_validated(
    api: AsyncClient, db_session: AsyncSession, google: StubGoogleClient
) -> None:
    event, _ = await make_event(db_session)
    await db_session.commit()
    admin = await sign_in_as(api, google, await seed_admin(db_session))
    url = f"/api/v1/admin/events/{event.id}/lineup"

    blank = await api.put(url, headers=bearer(admin), json={"performers": [{"name": "   "}]})
    assert blank.status_code == 422
    too_many = await api.put(
        url, headers=bearer(admin), json={"performers": [{"name": f"P{i}"} for i in range(21)]}
    )
    assert too_many.status_code == 422
    missing = await api.put(
        "/api/v1/admin/events/00000000-0000-0000-0000-000000000000/lineup",
        headers=bearer(admin),
        json={"performers": []},
    )
    assert missing.status_code == 404


async def test_event_location_link_is_stored_shown_and_must_be_a_web_link(
    api: AsyncClient, db_session: AsyncSession, google: StubGoogleClient
) -> None:
    event, _ = await make_event(db_session)
    await db_session.commit()
    admin = await sign_in_as(api, google, await seed_admin(db_session))
    url = f"/api/v1/admin/events/{event.id}"

    assert (await api.get(f"/api/v1/events/{event.slug}")).json()["location_url"] is None

    ok = await api.patch(
        url, headers=bearer(admin), json={"location_url": "  https://maps.app.goo.gl/abc123  "}
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["location_url"] == "https://maps.app.goo.gl/abc123"
    shown = (await api.get(f"/api/v1/events/{event.slug}")).json()
    assert shown["location_url"] == "https://maps.app.goo.gl/abc123"

    for bad in ("javascript:alert(1)", "maps.google.com/x", "ftp://example.com/x", "https://a b"):
        refused = await api.patch(url, headers=bearer(admin), json={"location_url": bad})
        assert refused.status_code == 422, bad

    cleared = await api.patch(url, headers=bearer(admin), json={"location_url": "   "})
    assert cleared.status_code == 200 and cleared.json()["location_url"] is None


async def test_venue_details_are_saved_cleaned_limited_and_shown_on_the_event(
    api: AsyncClient, db_session: AsyncSession, google: StubGoogleClient
) -> None:
    event, _ = await make_event(db_session)
    venue_id = event.venue_id
    slug = event.slug
    await db_session.commit()
    admin = await sign_in_as(api, google, await seed_admin(db_session))
    url = f"/api/v1/admin/venues/{venue_id}"

    # A venue with nothing filled in has empty lists, not nulls, on the event page.
    bare = (await api.get(f"/api/v1/events/{slug}")).json()["venue"]
    assert bare["description"] is None and bare["image_urls"] == [] and bare["benefits"] == []

    saved = await api.patch(
        url,
        headers=bearer(admin),
        json={
            "description": "A restored mill hall.",
            "image_urls": ["https://res.cloudinary.com/demo/image/upload/a.jpg", "  "],
            "benefits": ["  Free parking ", "", "Step-free access"],
        },
    )
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["image_urls"] == ["https://res.cloudinary.com/demo/image/upload/a.jpg"]
    assert body["benefits"] == ["Free parking", "Step-free access"]

    shown = (await api.get(f"/api/v1/events/{slug}")).json()["venue"]
    assert shown["description"] == "A restored mill hall."
    assert shown["benefits"] == ["Free parking", "Step-free access"]

    for bad in ({"benefits": [f"b{i}" for i in range(13)]}, {"image_urls": ["u"] * 9}):
        assert (await api.patch(url, headers=bearer(admin), json=bad)).status_code == 422
    # null clears; it must not crash
    cleared = await api.patch(
        url, headers=bearer(admin), json={"description": None, "image_urls": None, "benefits": None}
    )
    assert cleared.status_code == 200 and cleared.json()["benefits"] == []


async def test_a_past_event_is_listed_as_past_and_is_not_on_sale(
    api: AsyncClient, db_session: AsyncSession
) -> None:
    ahead, _ = await make_event(db_session)
    gone, _ = await make_event(db_session)
    ahead_slug, gone_slug = ahead.slug, gone.slug
    await db_session.execute(
        sa.text("UPDATE events SET starts_at = now() - interval '2 days' WHERE slug = :s"),
        {"s": gone_slug},
    )
    await db_session.commit()
    db_session.expire_all()  # the raw UPDATE bypassed the ORM's copy of the event

    upcoming = (await api.get(f"/api/v1/events/{ahead_slug}")).json()
    assert upcoming["is_past"] is False and upcoming["on_sale"] is True

    past = (await api.get(f"/api/v1/events/{gone_slug}")).json()
    assert past["is_past"] is True and past["on_sale"] is False

    past_list = (await api.get("/api/v1/events?past=true&size=100")).json()["items"]
    upcoming_list = (await api.get("/api/v1/events?size=100")).json()["items"]
    assert gone_slug in [e["slug"] for e in past_list]
    assert gone_slug not in [e["slug"] for e in upcoming_list]
    assert ahead_slug in [e["slug"] for e in upcoming_list]
