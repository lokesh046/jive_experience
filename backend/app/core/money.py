"""Money handling.

Rule: money is stored and transported as an **integer number of minor units**
(paise for INR). Floats are never used for money anywhere in this codebase, and
no rupee value is ever reconstructed by multiplying a float.

Payment gateways (Razorpay and Cashfree alike) and this database therefore
agree on exactly one representation, which removes a whole class of
reconciliation bugs.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

MINOR_UNITS_PER_MAJOR = 100
"""INR has two decimal places: 1 rupee = 100 paise."""


def rupees_to_paise(amount: Decimal | int | str) -> int:
    """Convert a rupee amount to paise, rounding half-up at the paisa."""
    quantised = Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return int(quantised * MINOR_UNITS_PER_MAJOR)


def paise_to_rupees(paise: int) -> Decimal:
    """Convert paise to an exact rupee Decimal (never a float)."""
    return (Decimal(paise) / MINOR_UNITS_PER_MAJOR).quantize(Decimal("0.01"))


def format_inr(paise: int) -> str:
    """Render paise for display, e.g. 250000 -> '₹2,500.00'."""
    return f"₹{paise_to_rupees(paise):,.2f}"


def percentage_of(paise: int, percent: Decimal | int | str) -> int:
    """A percentage of an amount in paise, rounded half-up to whole paise.

    Used by refund policies (e.g. "75% refund before the cutoff"). Returning
    whole paise keeps the refunded total exactly reconcilable against the
    captured total.
    """
    value = (Decimal(paise) * Decimal(str(percent)) / Decimal(100)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    return int(value)
