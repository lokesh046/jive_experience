"""The event lineup: admin sets it as one ordered list, the public page shows it."""

from __future__ import annotations

import pytest
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
