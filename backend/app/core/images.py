"""Profile-photo processing.

Uploads are untrusted files. The only safe way to accept one is to decode it,
throw the original away and store what *we* encoded: that removes embedded
scripts, metadata (including GPS location) and any format trick in one step.
"""

from __future__ import annotations

import io

from PIL import Image, ImageOps, UnidentifiedImageError

# A hard ceiling on decoded size, so a small file that expands to gigabytes of
# pixels (a "decompression bomb") is refused instead of exhausting memory.
MAX_PIXELS = 25_000_000
Image.MAX_IMAGE_PIXELS = MAX_PIXELS

MAX_UPLOAD_BYTES = 2 * 1024 * 1024
AVATAR_SIZE = 256
ALLOWED_FORMATS = frozenset({"JPEG", "PNG", "WEBP"})
AVATAR_CONTENT_TYPE = "image/webp"


class InvalidImageError(ValueError):
    """The upload is not an acceptable image."""


def make_avatar(data: bytes) -> bytes:
    """Return a square 256px WebP made from an uploaded JPEG, PNG or WebP."""
    try:
        with Image.open(io.BytesIO(data)) as probe:
            if probe.format not in ALLOWED_FORMATS:
                raise InvalidImageError("Use a JPEG, PNG or WebP image.")
            # Pillow only *warns* up to twice its own limit, so enforce ours before decoding.
            if probe.width * probe.height > MAX_PIXELS:
                raise InvalidImageError("That image is too large. Use one under 25 megapixels.")
            image = ImageOps.exif_transpose(probe)  # respect the phone's rotation
            image.load()
    except InvalidImageError:
        raise
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, ValueError) as exc:
        raise InvalidImageError("That file is not a readable image.") from exc

    if image.mode in ("RGBA", "LA", "P"):
        flat = Image.new("RGB", image.size, (0, 0, 0))
        flat.paste(image.convert("RGBA"), mask=image.convert("RGBA").getchannel("A"))
        image = flat
    else:
        image = image.convert("RGB")

    square = ImageOps.fit(image, (AVATAR_SIZE, AVATAR_SIZE), Image.Resampling.LANCZOS)
    out = io.BytesIO()
    square.save(out, format="WEBP", quality=82, method=4)  # no EXIF: metadata is not copied
    return out.getvalue()
