"""Profile-photo processing: what comes out must be safe whatever goes in."""

from __future__ import annotations

import io

import pytest
from PIL import Image

from app.core.images import AVATAR_SIZE, InvalidImageError, make_avatar


def _encode(image: Image.Image, fmt: str, **kwargs: object) -> bytes:
    out = io.BytesIO()
    image.save(out, format=fmt, **kwargs)
    return out.getvalue()


def test_result_is_a_square_webp_of_the_standard_size() -> None:
    wide = Image.new("RGB", (800, 300), (200, 40, 40))
    result = Image.open(io.BytesIO(make_avatar(_encode(wide, "PNG"))))
    assert result.format == "WEBP"
    assert result.size == (AVATAR_SIZE, AVATAR_SIZE)


@pytest.mark.parametrize("fmt", ["JPEG", "PNG", "WEBP"])
def test_accepts_the_three_allowed_formats(fmt: str) -> None:
    image = Image.new("RGB", (64, 64), (10, 20, 30))
    assert make_avatar(_encode(image, fmt))


def test_transparency_is_flattened() -> None:
    clear = Image.new("RGBA", (64, 64), (255, 255, 255, 0))
    result = Image.open(io.BytesIO(make_avatar(_encode(clear, "PNG"))))
    assert result.mode == "RGB"


def test_metadata_is_not_carried_over() -> None:
    image = Image.new("RGB", (64, 64), (1, 2, 3))
    exif = Image.Exif()
    exif[0x010E] = "secret description"  # ImageDescription
    result = Image.open(io.BytesIO(make_avatar(_encode(image, "JPEG", exif=exif))))
    assert len(result.getexif()) == 0


def test_rejects_other_image_formats() -> None:
    gif = _encode(Image.new("P", (16, 16)), "GIF")
    with pytest.raises(InvalidImageError):
        make_avatar(gif)


@pytest.mark.parametrize(
    "junk", [b"", b"not an image", b"<svg xmlns='http://www.w3.org/2000/svg'/>"]
)
def test_rejects_things_that_are_not_images(junk: bytes) -> None:
    with pytest.raises(InvalidImageError):
        make_avatar(junk)


def test_rejects_a_decompression_bomb() -> None:
    # A few KB on disk, 36 million pixels once decoded.
    bomb = _encode(Image.new("1", (6000, 6000)), "PNG")
    assert len(bomb) < 100_000
    with pytest.raises(InvalidImageError):
        make_avatar(bomb)
