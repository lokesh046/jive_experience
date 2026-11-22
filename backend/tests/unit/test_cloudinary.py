import hashlib

from pydantic import SecretStr

from app.core.cloudinary import sign_upload


def test_signature_matches_cloudinarys_documented_scheme() -> None:
    out = sign_upload(
        cloud_name="demo", api_key="k", api_secret=SecretStr("s3cret"), now=1700000000
    )
    expected = hashlib.sha1(
        b"allowed_formats=jpg,png,webp&folder=jive/events&timestamp=1700000000s3cret"
    ).hexdigest()
    assert out["signature"] == expected
    assert "s3cret" not in str(out)
    assert out["upload_url"] == "https://api.cloudinary.com/v1_1/demo/image/upload"
