"""The archive: photos of past nights, edited by admins and read by everyone."""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.conftest import customer_session, seed_admin, sign_in_as
from tests.integration.google_stub import StubGoogleClient

pytestmark = pytest.mark.integration

ADMIN = "/api/v1/admin/archive"
PUBLIC = "/api/v1/archive"


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
async def clean(db_session: AsyncSession):  # type: ignore[no-untyped-def]
    await db_session.execute(sa.text("DELETE FROM archive_items"))
    await db_session.commit()
    yield
    await db_session.execute(sa.text("DELETE FROM archive_items"))
    await db_session.commit()


def photo(n: int) -> str:
    return f"https://img.example/{n}.jpg"


async def test_admins_add_edit_reorder_hide_and_delete_archive_photos(
    api: AsyncClient, db_session: AsyncSession, google: StubGoogleClient
) -> None:
    admin = await sign_in_as(api, google, await seed_admin(db_session))
    ids = []
    for n, caption in enumerate(("  Vinyl Salon, March 2027  ", "Resonance in ruin", None)):
        made = await api.post(
            ADMIN, headers=bearer(admin), json={"caption": caption, "photo_url": photo(n)}
        )
        assert made.status_code == 201, made.text
        ids.append(made.json()["id"])
    listed = (await api.get(ADMIN, headers=bearer(admin))).json()
    assert [i["caption"] for i in listed] == ["Vinyl Salon, March 2027", "Resonance in ruin", None]

    public = (await api.get(PUBLIC)).json()
    assert [i["photo_url"] for i in public] == [photo(0), photo(1), photo(2)]
    flipped = await api.put(ADMIN + "/order", headers=bearer(admin), json={"ids": ids[::-1]})
    assert [i["photo_url"] for i in flipped.json()] == [photo(2), photo(1), photo(0)]
    assert [i["photo_url"] for i in (await api.get(PUBLIC)).json()] == [
        photo(2),
        photo(1),
        photo(0),
    ]

    hidden = await api.patch(
        f"{ADMIN}/{ids[1]}", headers=bearer(admin), json={"show_on_home": False}
    )
    assert hidden.json()["show_on_home"] is False
    assert [i["photo_url"] for i in (await api.get(PUBLIC)).json()] == [photo(2), photo(0)]
    assert len((await api.get(ADMIN, headers=bearer(admin))).json()) == 3

    swapped = await api.patch(
        f"{ADMIN}/{ids[0]}", headers=bearer(admin), json={"photo_url": photo(9), "caption": "  "}
    )
    assert swapped.json()["photo_url"] == photo(9) and swapped.json()["caption"] is None
    assert (await api.delete(f"{ADMIN}/{ids[0]}", headers=bearer(admin))).status_code == 204
    assert (await api.delete(f"{ADMIN}/{ids[0]}", headers=bearer(admin))).status_code == 404
    audited = (
        await db_session.execute(
            sa.text("SELECT count(*) FROM audit_logs WHERE action LIKE 'archive.%'")
        )
    ).scalar_one()
    assert audited >= 6


async def test_a_photo_can_be_replaced_but_never_removed(
    api: AsyncClient, db_session: AsyncSession, google: StubGoogleClient
) -> None:
    admin = await sign_in_as(api, google, await seed_admin(db_session))
    item = (await api.post(ADMIN, headers=bearer(admin), json={"photo_url": photo(1)})).json()
    cleared = await api.patch(
        f"{ADMIN}/{item['id']}", headers=bearer(admin), json={"photo_url": ""}
    )
    assert cleared.status_code in (409, 422)
    assert (await api.get(ADMIN, headers=bearer(admin))).json()[0]["photo_url"] == photo(1)


async def test_the_homepage_shows_at_most_six(
    api: AsyncClient, db_session: AsyncSession, google: StubGoogleClient
) -> None:
    admin = await sign_in_as(api, google, await seed_admin(db_session))
    for n in range(8):
        await api.post(ADMIN, headers=bearer(admin), json={"photo_url": photo(n)})
    assert len((await api.get(PUBLIC)).json()) == 6
    assert len((await api.get(ADMIN, headers=bearer(admin))).json()) == 8


async def test_the_order_must_list_every_item_once(
    api: AsyncClient, db_session: AsyncSession, google: StubGoogleClient
) -> None:
    admin = await sign_in_as(api, google, await seed_admin(db_session))
    a = (await api.post(ADMIN, headers=bearer(admin), json={"photo_url": photo(1)})).json()["id"]
    b = (await api.post(ADMIN, headers=bearer(admin), json={"photo_url": photo(2)})).json()["id"]
    for bad in ([a], [a, a]):
        assert (
            await api.put(ADMIN + "/order", headers=bearer(admin), json={"ids": bad})
        ).status_code in (409, 422)
    assert (
        await api.put(ADMIN + "/order", headers=bearer(admin), json={"ids": [b, a]})
    ).status_code == 200


async def test_bad_input_and_non_admins_are_refused(
    api: AsyncClient, db_session: AsyncSession, google: StubGoogleClient
) -> None:
    assert (await api.post(ADMIN, json={"photo_url": photo(1)})).status_code == 401
    customer = await customer_session(api, google)
    assert (
        await api.post(ADMIN, headers=bearer(customer["access"]), json={"photo_url": photo(1)})
    ).status_code == 403
    admin = await sign_in_as(api, google, await seed_admin(db_session))
    for bad in (
        {},
        {"photo_url": "  "},
        {"photo_url": "javascript:alert(1)"},
        {"photo_url": photo(1), "caption": "x" * 201},
    ):
        assert (await api.post(ADMIN, headers=bearer(admin), json=bad)).status_code == 422
    assert (await api.get(PUBLIC)).status_code == 200
