"""Payment provider contract.

**The provider is not chosen yet** — Razorpay or Cashfree; see
`docs/open-decisions.md`. Everything above this file is written against the
protocol below, so adding the real provider means implementing four methods
and setting `PAYMENT_PROVIDER`. No service, router or table changes.

What is deliberately *not* abstracted: signature verification and webhook
parsing differ materially between providers, so each adapter owns its own. The
shared code only ever sees the normalised results defined here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol

from app.core.errors import ServiceUnavailableError


class ProviderName(StrEnum):
    RAZORPAY = "razorpay"
    CASHFREE = "cashfree"
    UNCONFIGURED = "unconfigured"


@dataclass(frozen=True, slots=True)
class CheckoutOrder:
    """What the client needs to open the provider's hosted checkout."""

    provider: str
    provider_order_id: str
    amount_paise: int
    currency: str
    # Provider-specific fields the frontend SDK needs (key id, session token).
    # Never includes the client secret.
    checkout_payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class VerifiedPayment:
    """A payment confirmed by asking the provider, not by trusting the client."""

    provider_payment_id: str
    provider_order_id: str
    amount_paise: int
    currency: str
    succeeded: bool
    provider_status: str
    method: str | None = None
    failure_reason: str | None = None


@dataclass(frozen=True, slots=True)
class WebhookEnvelope:
    """A verified webhook, normalised across providers."""

    provider_event_id: str
    event_type: str
    provider_payment_id: str | None
    provider_order_id: str | None
    amount_paise: int | None
    succeeded: bool
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class RefundResult:
    provider_refund_id: str
    status: str
    # Providers settle asynchronously; `completed` means the money has moved,
    # not that the request was accepted.
    completed: bool
    failure_reason: str | None = None


class PaymentProvider(Protocol):
    """What a gateway adapter must do."""

    name: str

    async def create_order(
        self, *, amount_paise: int, currency: str, reference: str, idempotency_key: str
    ) -> CheckoutOrder: ...

    async def fetch_payment(self, provider_payment_id: str) -> VerifiedPayment:
        """Ask the provider for the truth about a payment.

        Used both for checkout verification and for reconciling payments whose
        webhook never arrived.
        """
        ...

    def parse_webhook(self, *, body: bytes, headers: dict[str, str]) -> WebhookEnvelope:
        """Verify the signature and normalise the event.

        Must raise rather than return for an unverified signature — an
        unsigned webhook is an attacker claiming a payment succeeded.
        """
        ...

    async def refund(
        self, *, provider_payment_id: str, amount_paise: int, idempotency_key: str
    ) -> RefundResult: ...


class UnconfiguredPaymentProvider:
    """Used until a provider is chosen.

    Every operation refuses clearly instead of pretending to work. This is the
    safe default: a stub that silently "succeeded" would confirm bookings and
    issue tickets for money that was never taken.
    """

    name = ProviderName.UNCONFIGURED.value

    def _refuse(self) -> ServiceUnavailableError:
        return ServiceUnavailableError(
            "Online payment is not configured on this server.",
            code="PAYMENT_PROVIDER_NOT_CONFIGURED",
        )

    async def create_order(
        self, *, amount_paise: int, currency: str, reference: str, idempotency_key: str
    ) -> CheckoutOrder:
        raise self._refuse()

    async def fetch_payment(self, provider_payment_id: str) -> VerifiedPayment:
        raise self._refuse()

    def parse_webhook(self, *, body: bytes, headers: dict[str, str]) -> WebhookEnvelope:
        raise self._refuse()

    async def refund(
        self, *, provider_payment_id: str, amount_paise: int, idempotency_key: str
    ) -> RefundResult:
        raise self._refuse()


_provider: PaymentProvider | None = None


def get_payment_provider(configured_name: str | None) -> PaymentProvider:
    """Return the configured adapter, or the refusing default.

    When the provider is chosen, add its adapter here. Nothing else changes.
    """
    global _provider
    if _provider is None:
        if configured_name in (None, "", ProviderName.UNCONFIGURED.value):
            _provider = UnconfiguredPaymentProvider()
        else:
            # Razorpay / Cashfree adapters land here once the merchant
            # account exists. Until then an explicit name is a config error,
            # not something to guess at.
            raise RuntimeError(
                f"PAYMENT_PROVIDER={configured_name!r} has no adapter yet. "
                "Implement it in app/services/payment_provider.py."
            )
    return _provider


def set_payment_provider(provider: PaymentProvider | None) -> None:
    """Replace the adapter — used by tests and by the composition root."""
    global _provider
    _provider = provider
