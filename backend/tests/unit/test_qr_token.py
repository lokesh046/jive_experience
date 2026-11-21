"""QR token derivation.

The contract the customer experience depends on: the same code every time it
is asked for, impossible to guess without the key, and distinct per ticket.
"""

from __future__ import annotations

import uuid

from app.core.config import Settings
from app.core.security import derive_qr_token, hash_refresh_token


def test_the_same_ticket_always_yields_the_same_code() -> None:
    """The whole point: a customer can reopen their ticket on a new phone,
    days later, and get the code that is in the database."""
    ticket_id = uuid.uuid4()
    first = derive_qr_token(ticket_id, secret="k" * 64)
    second = derive_qr_token(ticket_id, secret="k" * 64)
    assert first == second


def test_different_tickets_yield_different_codes() -> None:
    secret = "k" * 64
    codes = {derive_qr_token(uuid.uuid4(), secret=secret) for _ in range(200)}
    assert len(codes) == 200


def test_the_code_depends_on_the_key() -> None:
    """Knowing a ticket id must not be enough to produce its code."""
    ticket_id = uuid.uuid4()
    assert derive_qr_token(ticket_id, secret="a" * 64) != derive_qr_token(
        ticket_id, secret="b" * 64
    )


def test_the_code_does_not_leak_the_ticket_id() -> None:
    ticket_id = uuid.uuid4()
    code = derive_qr_token(ticket_id, secret="k" * 64)
    assert str(ticket_id) not in code
    assert ticket_id.hex not in code


def test_the_code_is_full_entropy_and_url_safe() -> None:
    """256 bits, and safe to put in a QR or a URL without escaping."""
    code = derive_qr_token(uuid.uuid4(), secret="k" * 64)
    assert len(code) == 43  # 32 bytes, base64url, unpadded
    assert all(c.isalnum() or c in "-_" for c in code)


def test_the_stored_hash_is_not_the_code() -> None:
    """A database disclosure must not yield scannable tickets."""
    code = derive_qr_token(uuid.uuid4(), secret="k" * 64)
    stored = hash_refresh_token(code)
    assert stored != code
    assert len(stored) == 64


def test_qr_secret_falls_back_to_the_signing_key() -> None:
    settings = Settings(secret_key="s" * 64)
    assert settings.qr_secret == "s" * 64


def test_a_dedicated_qr_key_is_used_when_set() -> None:
    """Session keys should be rotatable without voiding every live ticket."""
    settings = Settings(secret_key="s" * 64, qr_signing_key="q" * 64)
    assert settings.qr_secret == "q" * 64
