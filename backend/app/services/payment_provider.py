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


class ProviderPaymentState(StrEnum):
    """A gateway payment result, normalised.

    Three states, not a boolean. "Authorized but not captured" is neither
    success nor failure: the money is held, not taken. Collapsing it into
    `succeeded=False` would mark a live payment FAILED and refund a customer
    who is about to be charged correctly.
    """

    SUCCEEDED = "SUCCEEDED"
    PENDING = "PENDING"
    FAILED = "FAILED"


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
    state: ProviderPaymentState
    provider_status: str
    method: str | None = None
    failure_reason: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.state is ProviderPaymentState.SUCCEEDED

    @property
    def failed(self) -> bool:
        return self.state is ProviderPaymentState.FAILED


@dataclass(frozen=True, slots=True)
class WebhookEnvelope:
    """A verified webhook, normalised across providers."""

    provider_event_id: str
    event_type: str
    provider_payment_id: str | None
    provider_order_id: str | None
    amount_paise: int | None
    state: ProviderPaymentState
    payload: dict[str, Any]

    @property
    def succeeded(self) -> bool:
        return self.state is ProviderPaymentState.SUCCEEDED


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

    async def fetch_payments_for_order(self, provider_order_id: str) -> list[VerifiedPayment]:
        """Every payment attempt against an order.

        Needed when a customer pays and closes the tab before the callback:
        we hold the order we created and nothing else, so this is the only
        way left to discover the payment.
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

    def verify_checkout_signature(
        self, *, provider_order_id: str, provider_payment_id: str, signature: str
    ) -> bool:
        """Check the signature the client returned from hosted checkout.

        Defence in depth only — the authoritative answer always comes from
        asking the provider. A provider without client-side signatures may
        return True.
        """
        ...


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

    async def fetch_payments_for_order(self, provider_order_id: str) -> list[VerifiedPayment]:
        raise self._refuse()

    def parse_webhook(self, *, body: bytes, headers: dict[str, str]) -> WebhookEnvelope:
        raise self._refuse()

    async def refund(
        self, *, provider_payment_id: str, amount_paise: int, idempotency_key: str
    ) -> RefundResult:
        raise self._refuse()

    def verify_checkout_signature(
        self, *, provider_order_id: str, provider_payment_id: str, signature: str
    ) -> bool:
        raise self._refuse()


_provider: PaymentProvider | None = None


def get_payment_provider(configured_name: str | None, settings: Any = None) -> PaymentProvider:
    """Return the configured adapter, or the refusing default."""
    global _provider
    if _provider is not None:
        return _provider

    if configured_name in (None, "", ProviderName.UNCONFIGURED.value):
        _provider = UnconfiguredPaymentProvider()
        return _provider

    if configured_name == ProviderName.RAZORPAY.value:
        from app.core.config import get_settings
        from app.services.providers.razorpay import RazorpayProvider

        _provider = RazorpayProvider(settings or get_settings())
        return _provider

    raise RuntimeError(
        f"PAYMENT_PROVIDER={configured_name!r} has no adapter. "
        "Implement it under app/services/providers/."
    )


def set_payment_provider(provider: PaymentProvider | None) -> None:
    """Replace the adapter — used by tests and by the composition root."""
    global _provider
    _provider = provider
