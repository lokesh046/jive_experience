"""Make a key pair for browser push: `python -m scripts.make_vapid_keys`.

Put the two values in the environment (`VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`). The private key
signs each push, so keep it secret; changing the pair later makes every saved browser
subscription stop working until its owner turns notifications on again.
"""

from __future__ import annotations

import base64

from cryptography.hazmat.primitives import serialization
from py_vapid import Vapid01


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def main() -> None:
    vapid = Vapid01()
    vapid.generate_keys()
    private = vapid.private_key.private_numbers().private_value.to_bytes(32, "big")
    public = vapid.public_key.public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    print(f"VAPID_PUBLIC_KEY={_b64(public)}")
    print(f"VAPID_PRIVATE_KEY={_b64(private)}")


if __name__ == "__main__":
    main()
