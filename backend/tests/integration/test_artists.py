"""Artists: the company's own homepage list, edited by admins and read by everyone."""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.conftest import customer_session, seed_admin, sign_in_as
from tests.integration.google_stub import StubGoogleClient

pytestmark = pytest.mark.integration

ADMIN = "/api/v1/admin/artists"
PUBLIC = "/api/v1/artists"


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
async def clean(db_session: AsyncSession):  # type: ignore[no-untyped-def]
    await db_session.execute(sa.text("DELETE FROM artists"))
    await db_session.commit()
    yield
    await db_session.execute(sa.text("DELETE FROM artists"))
    await db_session.commit()


async def test_admins_add_edit_reorder_hide_and_delete_artists(
    api: AsyncClient, db_session: AsyncSession, google: StubGoogleClient
) -> None:
    admin = await sign_in_as(api, google, await seed_admin(db_session))
    ids = []
    for name in ("  Kohra  ", "Anyasa", "Komorebi"):
        made = await api.post(
            ADMIN,
            headers=bearer(admin),
            json={"name": name, "note": "Solo cello", "photo_url": "https://img.example/a.jpg"},
        )
        assert made.status_code == 201, made.text
        ids.append(made.json()["id"])
    listed = (await api.get(ADMIN, headers=bearer(admin))).json()
    assert [a["name"] for a in listed] == [
        "Kohra",
        "Anyasa",
        "Komorebi",
    ]  # trimmed, in the order added

    # The public list follows the admin's order.
    assert [a["name"] for a in (await api.get(PUBLIC)).json()] == ["Kohra", "Anyasa", "Komorebi"]
    flipped = await api.put(ADMIN + "/order", headers=bearer(admin), json={"ids": ids[::-1]})
    assert [a["name"] for a in flipped.json()] == ["Komorebi", "Anyasa", "Kohra"]
    assert [a["name"] for a in (await api.get(PUBLIC)).json()] == ["Komorebi", "Anyasa", "Kohra"]

    # Hiding removes someone from the homepage but keeps them in the list.
    hidden = await api.patch(
        f"{ADMIN}/{ids[1]}", headers=bearer(admin), json={"show_on_home": False}
    )
    assert hidden.status_code == 200 and hidden.json()["show_on_home"] is False
    assert [a["name"] for a in (await api.get(PUBLIC)).json()] == ["Komorebi", "Kohra"]
    assert len((await api.get(ADMIN, headers=bearer(admin))).json()) == 3

    # A blank note clears it; an edit changes only what was sent.
    edited = await api.patch(f"{ADMIN}/{ids[0]}", headers=bearer(admin), json={"note": "   "})
    assert edited.json()["note"] is None and edited.json()["name"] == "Kohra"
    assert (await api.delete(f"{ADMIN}/{ids[0]}", headers=bearer(admin))).status_code == 204
    assert (await api.delete(f"{ADMIN}/{ids[0]}", headers=bearer(admin))).status_code == 404
    audited = (
        await db_session.execute(
            sa.text("SELECT count(*) FROM audit_logs WHERE action LIKE 'artist.%'")
        )
    ).scalar_one()
    assert audited >= 6


async def test_the_order_must_list_every_artist_once(
    api: AsyncClient, db_session: AsyncSession, google: StubGoogleClient
) -> None:
    admin = await sign_in_as(api, google, await seed_admin(db_session))
    a = (await api.post(ADMIN, headers=bearer(admin), json={"name": "A"})).json()["id"]
    b = (await api.post(ADMIN, headers=bearer(admin), json={"name": "B"})).json()["id"]
    assert (
        await api.put(ADMIN + "/order", headers=bearer(admin), json={"ids": [a]})
    ).status_code == 422
    assert (
        await api.put(ADMIN + "/order", headers=bearer(admin), json={"ids": [a, a]})
    ).status_code == 422
    assert (
        await api.put(ADMIN + "/order", headers=bearer(admin), json={"ids": [b, a]})
    ).status_code == 200


async def test_bad_input_and_non_admins_are_refused(
    api: AsyncClient, db_session: AsyncSession, google: StubGoogleClient
) -> None:
    assert (await api.post(ADMIN, json={"name": "X"})).status_code == 401
    customer = await customer_session(api, google)
    assert (
        await api.post(ADMIN, headers=bearer(customer["access"]), json={"name": "X"})
    ).status_code == 403
    assert (await api.get(ADMIN, headers=bearer(customer["access"]))).status_code == 403
    admin = await sign_in_as(api, google, await seed_admin(db_session))
    for bad in (
        {"name": "   "},
        {"name": "X", "photo_url": "javascript:alert(1)"},
        {"name": "x" * 121},
    ):
        assert (await api.post(ADMIN, headers=bearer(admin), json=bad)).status_code == 422
    # The public list needs no sign-in and shows nothing private.
    assert (await api.get(PUBLIC)).status_code == 200
