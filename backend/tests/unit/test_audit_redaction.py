"""Secrets must never reach the audit trail."""

from __future__ import annotations

import pytest

from app.services.audit import REDACTED, redact


def test_none_passes_through() -> None:
    assert redact(None) is None


@pytest.mark.parametrize(
    "key",
    [
        "password",
        "new_password",
        "current_password",
        "password_hash",
        "refresh_token",
        "id_token",
        "client_secret",
        "token_hash",
        "secret",
        "api_key",
        "cvv",
    ],
)
def test_sensitive_keys_are_redacted(key: str) -> None:
    assert redact({key: "super-secret-value"}) == {key: REDACTED}


def test_redaction_is_case_insensitive() -> None:
    assert redact({"Password": "x", "API_KEY": "y"}) == {
        "Password": REDACTED,
        "API_KEY": REDACTED,
    }


def test_nested_structures_are_redacted() -> None:
    cleaned = redact({"user": {"email": "a@b.com", "password": "hunter2"}})
    assert cleaned == {"user": {"email": "a@b.com", "password": REDACTED}}


def test_ordinary_fields_survive() -> None:
    payload = {"status": "SUSPENDED", "reason": "chargeback", "count": 3}
    assert redact(payload) == payload
