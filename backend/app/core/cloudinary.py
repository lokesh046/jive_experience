"""Signed uploads for Cloudinary.

The browser sends the photo straight to Cloudinary, so image bytes never pass
through this API. What it needs from us is a signature proving an administrator
allowed this exact upload. The signature covers the folder, format list and
timestamp, so it cannot be reused for another folder, and it expires with the
timestamp. The API secret never leaves the server.
"""

from __future__ import annotations

import hashlib
import time
from typing import Final

import httpx
from pydantic import SecretStr

from app.core.config import Settings
from app.core.errors import ServiceUnavailableError

ALLOWED_FORMATS: Final = "jpg,png,webp"
FOLDER: Final = "jive/events"


def sign_upload(
    *, cloud_name: str, api_key: str, api_secret: SecretStr, now: int | None = None
) -> dict[str, str | int]:
    timestamp = int(time.time()) if now is None else now
    # Cloudinary signs the sorted `key=value` pairs joined by `&`, plus the secret.
    params = {"allowed_formats": ALLOWED_FORMATS, "folder": FOLDER, "timestamp": timestamp}
    to_sign = "&".join(f"{k}={params[k]}" for k in sorted(params))
    signature = hashlib.sha1((to_sign + api_secret.get_secret_value()).encode()).hexdigest()
    return {
        "cloud_name": cloud_name,
        "api_key": api_key,
        "timestamp": timestamp,
        "signature": signature,
        "folder": FOLDER,
        "allowed_formats": ALLOWED_FORMATS,
        "upload_url": f"https://api.cloudinary.com/v1_1/{cloud_name}/image/upload",
    }


AVATAR_FOLDER: Final = "jive/avatars"


def _sign(params: dict[str, str | int], secret: SecretStr) -> str:
    to_sign = "&".join(f"{k}={params[k]}" for k in sorted(params))
    return hashlib.sha1((to_sign + secret.get_secret_value()).encode()).hexdigest()


def _form(params: dict[str, str | int], key: str, secret: SecretStr) -> dict[str, str]:
    return {
        **{k: str(v) for k, v in params.items()},
        "api_key": key,
        "signature": _sign(params, secret),
    }


def _credentials(settings: Settings) -> tuple[str, str, SecretStr]:
    if not (
        settings.cloudinary_cloud_name
        and settings.cloudinary_api_key
        and settings.cloudinary_api_secret
    ):
        raise ServiceUnavailableError(
            "Photo uploads are not set up.", code="UPLOADS_NOT_CONFIGURED"
        )
    return (
        settings.cloudinary_cloud_name,
        settings.cloudinary_api_key,
        settings.cloudinary_api_secret,
    )


async def upload_avatar(settings: Settings, *, user_id: str, data: bytes) -> str:
    """Store an already-processed avatar; one fixed public id per user, so a new
    photo replaces the old one and the CDN cache is invalidated."""
    cloud, key, secret = _credentials(settings)
    params: dict[str, str | int] = {
        "folder": AVATAR_FOLDER,
        "invalidate": "true",
        "overwrite": "true",
        "public_id": user_id,
        "timestamp": int(time.time()),
    }
    form = {
        **{k: str(v) for k, v in params.items()},
        "api_key": key,
        "signature": _sign(params, secret),
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            res = await client.post(
                f"https://api.cloudinary.com/v1_1/{cloud}/image/upload",
                data=form,
                files={"file": ("avatar.webp", data, "image/webp")},
            )
        res.raise_for_status()
        return str(res.json()["secure_url"])
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        raise ServiceUnavailableError(
            "The photo could not be saved. Please try again.", code="UPLOAD_FAILED"
        ) from exc


async def delete_avatar(settings: Settings, *, user_id: str) -> None:
    """Best effort: a failure leaves an orphan file, never a broken profile."""
    cloud, key, secret = _credentials(settings)
    params: dict[str, str | int] = {
        "invalidate": "true",
        "public_id": f"{AVATAR_FOLDER}/{user_id}",
        "timestamp": int(time.time()),
    }
    form = {
        **{k: str(v) for k, v in params.items()},
        "api_key": key,
        "signature": _sign(params, secret),
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            await client.post(f"https://api.cloudinary.com/v1_1/{cloud}/image/destroy", data=form)
    except httpx.HTTPError:
        pass
