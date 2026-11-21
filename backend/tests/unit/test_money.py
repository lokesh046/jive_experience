"""Money is integer paise end to end — these tests pin that contract."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.money import format_inr, paise_to_rupees, percentage_of, rupees_to_paise


@pytest.mark.parametrize(
    ("rupees", "paise"),
    [("0", 0), ("1", 100), ("2500", 250_000), ("499.99", 49_999), ("0.01", 1)],
)
def test_rupees_to_paise(rupees: str, paise: int) -> None:
    assert rupees_to_paise(Decimal(rupees)) == paise


def test_rupees_to_paise_rounds_half_up() -> None:
    assert rupees_to_paise(Decimal("10.005")) == 1001
    assert rupees_to_paise(Decimal("10.004")) == 1000


def test_round_trip_is_lossless() -> None:
    assert paise_to_rupees(rupees_to_paise(Decimal("1234.56"))) == Decimal("1234.56")


def test_no_float_drift_on_a_classic_case() -> None:
    # 0.1 + 0.2 in floats is 0.30000000000000004; in paise it is exactly 30.
    assert rupees_to_paise("0.1") + rupees_to_paise("0.2") == 30


def test_format_inr() -> None:
    assert format_inr(250_000) == "₹2,500.00"
    assert format_inr(0) == "₹0.00"


@pytest.mark.parametrize(
    ("paise", "percent", "expected"),
    [
        (100_000, 100, 100_000),  # full refund
        (100_000, 75, 75_000),  # partial refund tier
        (100_000, 0, 0),  # past the cutoff
        (333, 50, 167),  # 166.5 rounds half-up
    ],
)
def test_percentage_of(paise: int, percent: int, expected: int) -> None:
    assert percentage_of(paise, percent) == expected


def test_full_refund_returns_exactly_the_captured_amount() -> None:
    captured = 123_457
    assert percentage_of(captured, 100) == captured


def test_split_percentages_can_round_up_by_one_paisa() -> None:
    """Documented caveat: a refund split across items must be computed as
    `total - already_refunded` for the final item, never as a second
    independent percentage, or it can exceed the captured amount by 1 paisa."""
    captured = 123_457
    half = percentage_of(captured, 50)
    assert half * 2 == captured + 1
    assert half + (captured - half) == captured
