"""Bootstrap CLI validation.

The CLI must accept exactly what the login endpoint accepts. If it is laxer,
it creates an administrator who can never sign in.
"""

from __future__ import annotations

import pytest

from app.cli import main, validate_email


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("ops@example.com", "ops@example.com"),
        ("Ops@Example.COM", "ops@example.com"),
        ("a.b+tag@sub.example.co.in", "a.b+tag@sub.example.co.in"),
    ],
)
def test_valid_emails_are_accepted_and_normalised(raw: str, expected: str) -> None:
    assert validate_email(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "ops@jive.test",  # reserved TLD — accepted by a naive check, refused at login
        "ops@localhost",
        "not-an-email",
        "@example.com",
        "ops@",
        "",
    ],
)
def test_invalid_emails_are_refused(raw: str) -> None:
    assert validate_email(raw) is None


def test_unknown_command_exits_nonzero() -> None:
    with pytest.raises(SystemExit):
        main(["nonsense"])


def test_create_admin_requires_email_and_name() -> None:
    with pytest.raises(SystemExit):
        main(["create-admin"])
