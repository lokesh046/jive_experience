"""Profile photo and profile edits, end to end."""

from __future__ import annotations

import io

import pytest
from httpx import AsyncClient
from PIL import Image

from app.core.images import MAX_UPLOAD_BYTES
from tests.integration.conftest import customer_session
from tests.integration.google_stub import StubGoogleClient

pytestmark = pytest.mark.integration

ME = "/api/v1/users/me"
AVATAR = f"{ME}/avatar"


def _png(size: tuple[int, int] = (500, 300)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, (90, 30, 140)).save(out, format="PNG")
    return out.getvalue()


async def _headers(api: AsyncClient, google: StubGoogleClient) -> dict[str, str]:
    session = await customer_session(api, google)
    return {"Authorization": f"Bearer {session['access']}"}


@pytest.fixture(autouse=True)
def fake_cloudinary(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[bytes]]:
    """Stands in for Cloudinary: records what would have been uploaded."""
    sent: dict[str, list[bytes]] = {"uploads": [], "deleted": []}

    async def upload(settings: object, *, user_id: str, data: bytes) -> str:
        sent["uploads"].append(data)
        return f"https://res.cloudinary.com/demo/image/upload/v{len(sent['uploads'])}/jive/avatars/{user_id}.webp"

    async def delete(settings: object, *, user_id: str) -> None:
        sent["deleted"].append(user_id.encode())

    monkeypatch.setattr("app.core.cloudinary.upload_avatar", upload)
    monkeypatch.setattr("app.core.cloudinary.delete_avatar", delete)
    return sent


async def test_upload_sends_a_clean_square_and_remove_deletes_it(
    api: AsyncClient, google: StubGoogleClient, fake_cloudinary: dict[str, list[bytes]]
) -> None:
    headers = await _headers(api, google)

    put = await api.put(AVATAR, content=_png(), headers=headers)
    assert put.status_code == 200, put.text
    assert put.json()["avatar_url"].startswith("https://res.cloudinary.com/")
    # Cloudinary only ever sees the processed 256px copy, not the original.
    assert Image.open(io.BytesIO(fake_cloudinary["uploads"][0])).size == (256, 256)

    gone = await api.delete(AVATAR, headers=headers)
    assert gone.status_code == 200
    assert gone.json()["avatar_url"] is None
    assert len(fake_cloudinary["deleted"]) == 1


async def test_replacing_a_photo_changes_the_url(
    api: AsyncClient, google: StubGoogleClient
) -> None:
    headers = await _headers(api, google)
    first = (await api.put(AVATAR, content=_png(), headers=headers)).json()["avatar_url"]
    second = (await api.put(AVATAR, content=_png((300, 500)), headers=headers)).json()["avatar_url"]
    assert first != second


async def test_oversized_upload_is_refused(api: AsyncClient, google: StubGoogleClient) -> None:
    headers = await _headers(api, google)
    response = await api.put(AVATAR, content=b"x" * (MAX_UPLOAD_BYTES + 1), headers=headers)
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "IMAGE_TOO_LARGE"


async def test_a_non_image_is_refused(api: AsyncClient, google: StubGoogleClient) -> None:
    headers = await _headers(api, google)
    response = await api.put(AVATAR, content=b"<script>alert(1)</script>", headers=headers)
    assert response.status_code in (400, 422)
    assert response.json()["error"]["code"] == "INVALID_IMAGE"


async def test_photo_requires_sign_in(api: AsyncClient) -> None:
    assert (await api.put(AVATAR, content=_png())).status_code == 401
    assert (await api.delete(AVATAR)).status_code == 401


async def test_name_can_be_changed_but_email_cannot(
    api: AsyncClient, google: StubGoogleClient
) -> None:
    headers = await _headers(api, google)
    before = (await api.get(ME, headers=headers)).json()

    patched = await api.patch(
        ME, json={"full_name": "  Aarav Mehta  ", "email": "evil@example.com"}, headers=headers
    )
    assert patched.status_code == 200
    assert patched.json()["full_name"] == "Aarav Mehta"
    assert patched.json()["email"] == before["email"]
