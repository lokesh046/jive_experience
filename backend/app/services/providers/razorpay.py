"""Razorpay adapter.

Implements the `PaymentProvider` protocol against the Razorpay v1 REST API.
Nothing above this file knows Razorpay exists.

Two signatures, two different secrets — the single most common way to get this
integration wrong:

* **Webhook** — `X-Razorpay-Signature`, HMAC-SHA256 over the **raw request
  body**, keyed with the *webhook secret* set in the dashboard.
* **Checkout return** — `razorpay_signature`, HMAC-SHA256 over
  `"{order_id}|{payment_id}"`, keyed with the *API key secret*.

The raw body matters: re-serialising parsed JSON changes whitespace and key
order, and every signature then fails.

Amounts are integers in paise throughout, which is what this codebase uses
internally, so no conversion happens anywhere.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from typing import Any

import httpx
import structlog

from app.core.config import Settings
from app.core.errors import (
    AuthenticationError,
    BusinessRuleError,
    ServiceUnavailableError,
)
from app.services.payment_provider import (
    CheckoutOrder,
    ProviderPaymentState,
    RefundResult,
    VerifiedPayment,
    WebhookEnvelope,
)

logger = structlog.get_logger(__name__)

API_BASE = "https://api.razorpay.com/v1"
TIMEOUT = httpx.Timeout(20.0, connect=5.0)

SIGNATURE_HEADER = "x-razorpay-signature"
EVENT_ID_HEADER = "x-razorpay-event-id"
REFUND_IDEMPOTENCY_HEADER = "X-Refund-Idempotency"

# Razorpay caps `receipt` at 40 characters and treats it as a dedupe key.
RECEIPT_MAX_LENGTH = 40

# The idempotency header accepts alphanumerics, hyphen and underscore only,
# and requires at least 10 characters.
IDEMPOTENCY_ALLOWED = re.compile(r"[^A-Za-z0-9_-]")
IDEMPOTENCY_MIN_LENGTH = 10

# Razorpay payment states. `authorized` means the money is held but not taken:
# neither a success nor a failure, and treating it as either is a real bug.
PAYMENT_STATE = {
    "captured": ProviderPaymentState.SUCCEEDED,
    "refunded": ProviderPaymentState.SUCCEEDED,
    "authorized": ProviderPaymentState.PENDING,
    "created": ProviderPaymentState.PENDING,
    "pending": ProviderPaymentState.PENDING,
    "failed": ProviderPaymentState.FAILED,
    "cancelled": ProviderPaymentState.FAILED,
}

# Razorpay refund states: `processed` is terminal success, `pending` means the
# bank has not settled it yet — which is why refunds are reconciled rather
# than assumed complete.
REFUND_COMPLETED = "processed"
REFUND_FAILED = "failed"


class RazorpayProvider:
    """Talks to Razorpay. Knows nothing about bookings or tickets."""

    name = "razorpay"

    def __init__(
        self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        if not settings.payment_key_id or not settings.payment_key_secret:
            raise RuntimeError(
                "PAYMENT_PROVIDER=razorpay requires PAYMENT_KEY_ID and PAYMENT_KEY_SECRET."
            )
        self._settings = settings
        self._key_id = settings.payment_key_id
        self._key_secret = settings.payment_key_secret.get_secret_value()
        self._webhook_secret = (
            settings.payment_webhook_secret.get_secret_value()
            if settings.payment_webhook_secret
            else None
        )
        # Injected by tests so no request ever leaves the machine.
        self._transport = transport

    @property
    def is_test_mode(self) -> bool:
        """Razorpay test keys are prefixed `rzp_test_`."""
        return self._key_id.startswith("rzp_test_")

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=API_BASE,
            auth=(self._key_id, self._key_secret),
            timeout=TIMEOUT,
            transport=self._transport,
        )

    # ------------------------------------------------------------ orders ---

    async def create_order(
        self, *, amount_paise: int, currency: str, reference: str, idempotency_key: str
    ) -> CheckoutOrder:
        """Create the order the hosted checkout is opened against.

        `receipt` carries our booking reference and is Razorpay's own dedupe
        key: creating twice with the same receipt is rejected rather than
        charging twice.
        """
        if amount_paise < 100:
            # Razorpay's documented floor is 100 paise.
            raise BusinessRuleError(
                "The minimum payable amount is ₹1.00.", code="AMOUNT_BELOW_MINIMUM"
            )

        payload = {
            "amount": amount_paise,
            "currency": currency,
            "receipt": reference[:RECEIPT_MAX_LENGTH],
            "notes": {"booking_reference": reference},
        }
        data = await self._post("/orders", payload)

        return CheckoutOrder(
            provider=self.name,
            provider_order_id=str(data["id"]),
            amount_paise=int(data["amount"]),
            currency=str(data["currency"]),
            # What Checkout.js needs. `key` is the publishable key id — never
            # the secret, which has no reason to reach a browser.
            checkout_payload={
                "key": self._key_id,
                "order_id": data["id"],
                "amount": data["amount"],
                "currency": data["currency"],
                "name": self._settings.app_name,
                "receipt": data.get("receipt"),
            },
        )

    # ---------------------------------------------------------- payments ---

    async def fetch_payment(self, provider_payment_id: str) -> VerifiedPayment:
        """Ask Razorpay what really happened to a payment.

        The authoritative check. Used both after the browser returns from
        checkout and by the reconciliation sweep for payments whose webhook
        never arrived.
        """
        data = await self._get(f"/payments/{provider_payment_id}")
        return self._to_verified_payment(data)

    def _to_verified_payment(self, data: dict[str, Any]) -> VerifiedPayment:
        status = str(data.get("status", "")).lower()
        state = PAYMENT_STATE.get(status, ProviderPaymentState.PENDING)
        if status and status not in PAYMENT_STATE:
            # An unknown state must never be read as success. Treating it as
            # pending means reconciliation asks again rather than confirming
            # a booking against a payment we do not understand.
            logger.warning("razorpay_unknown_payment_status", status=status)

        return VerifiedPayment(
            provider_payment_id=str(data.get("id", "")),
            provider_order_id=str(data.get("order_id") or ""),
            amount_paise=int(data.get("amount") or 0),
            currency=str(data.get("currency") or "INR"),
            state=state,
            provider_status=status,
            method=data.get("method"),
            failure_reason=data.get("error_description") or data.get("error_reason"),
        )

    async def fetch_payments_for_order(self, provider_order_id: str) -> list[VerifiedPayment]:
        """Every attempt against an order.

        Reconciliation's fallback when no payment id was ever recorded — the
        customer paid and closed the tab, so the order is all we hold.
        """
        data = await self._get(f"/orders/{provider_order_id}/payments")
        return [self._to_verified_payment(item) for item in data.get("items", [])]

    def verify_checkout_signature(
        self, *, provider_order_id: str, provider_payment_id: str, signature: str
    ) -> bool:
        """Verify what Checkout.js handed the browser.

        Signed with the **API key secret** over `order_id|payment_id`. This is
        a cheap first gate; `fetch_payment` is what actually decides, because
        a signature only proves the message came from Razorpay, not that the
        money moved.
        """
        expected = hmac.new(
            self._key_secret.encode(),
            f"{provider_order_id}|{provider_payment_id}".encode(),
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, signature)

    # ---------------------------------------------------------- webhooks ---

    def parse_webhook(self, *, body: bytes, headers: dict[str, str]) -> WebhookEnvelope:
        """Verify the signature over the raw body, then normalise the event.

        Signed with the **webhook secret**, which is a different secret from
        the API key. An unverified webhook is an attacker claiming a payment
        succeeded, so this raises rather than returning a result.
        """
        if not self._webhook_secret:
            raise ServiceUnavailableError(
                "Payment webhooks are not configured on this server.",
                code="WEBHOOK_SECRET_NOT_CONFIGURED",
            )

        signature = headers.get(SIGNATURE_HEADER) or headers.get(SIGNATURE_HEADER.title())
        if not signature:
            raise AuthenticationError(
                "Missing webhook signature.", code="WEBHOOK_SIGNATURE_MISSING"
            )

        expected = hmac.new(self._webhook_secret.encode(), body, hashlib.sha256).hexdigest()
        # Compared as bytes: `compare_digest` raises TypeError on a non-ASCII
        # str, and this header is attacker-controlled — so a junk signature
        # would surface as a 500 rather than a clean refusal.
        if not hmac.compare_digest(expected.encode(), signature.encode()):
            raise AuthenticationError(
                "Invalid webhook signature.", code="WEBHOOK_SIGNATURE_INVALID"
            )

        import json

        try:
            payload: dict[str, Any] = json.loads(body)
        except json.JSONDecodeError as exc:
            raise AuthenticationError(
                "Malformed webhook body.", code="WEBHOOK_BODY_INVALID"
            ) from exc

        event_type = str(payload.get("event", ""))
        entity = (
            payload.get("payload", {}).get("payment", {}).get("entity", {})
            if isinstance(payload.get("payload"), dict)
            else {}
        )

        # Razorpay's own per-delivery id. Retries of the same event reuse it,
        # which is exactly what the unique constraint downstream relies on.
        event_id = headers.get(EVENT_ID_HEADER) or headers.get(EVENT_ID_HEADER.title())
        if not event_id:
            # Fall back to the payment id plus event name so a redelivery
            # without the header still deduplicates.
            event_id = f"{event_type}:{entity.get('id', '')}"

        return WebhookEnvelope(
            provider_event_id=str(event_id),
            event_type=event_type,
            provider_payment_id=entity.get("id"),
            provider_order_id=entity.get("order_id"),
            amount_paise=int(entity["amount"]) if entity.get("amount") else None,
            state=self._to_verified_payment(entity).state
            if entity
            else ProviderPaymentState.PENDING,
            payload=payload,
        )

    # ----------------------------------------------------------- refunds ---

    async def refund(
        self, *, provider_payment_id: str, amount_paise: int, idempotency_key: str
    ) -> RefundResult:
        """Request a refund.

        `X-Refund-Idempotency` — Razorpay's refund-specific header, not the
        generic `Idempotency-Key`. Resending the same key with the same body
        returns the original refund instead of creating a second one, which is
        what makes the worker's retries safe.
        """
        data = await self._post(
            f"/payments/{provider_payment_id}/refund",
            {"amount": amount_paise, "speed": "normal"},
            headers={REFUND_IDEMPOTENCY_HEADER: self._idempotency_key(idempotency_key)},
        )

        status = str(data.get("status", "")).lower()
        return RefundResult(
            provider_refund_id=str(data.get("id", "")),
            status=status,
            # `pending` means the bank has not settled it. Only `processed` is
            # money actually returned, which is why nothing downstream marks a
            # booking refunded until then.
            completed=status == REFUND_COMPLETED,
            failure_reason=data.get("error_description") if status == REFUND_FAILED else None,
        )

    @staticmethod
    def _idempotency_key(raw: str) -> str:
        """Fit our key to Razorpay's rules.

        Ours look like `refund:<uuid>:<amount>`; the header allows only
        alphanumerics, hyphen and underscore, and needs at least 10
        characters. Substitution is deterministic, so the same logical refund
        always produces the same key — which is the entire point.
        """
        cleaned = IDEMPOTENCY_ALLOWED.sub("-", raw)
        if len(cleaned) < IDEMPOTENCY_MIN_LENGTH:
            cleaned = f"{cleaned}-{'0' * IDEMPOTENCY_MIN_LENGTH}"
        return cleaned[:64]

    # -------------------------------------------------------------- http ---

    async def _post(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        try:
            async with self._client() as client:
                response = await client.post(path, json=payload, headers=headers)
        except httpx.HTTPError as exc:
            logger.error("razorpay_request_failed", path=path, error=str(exc))
            raise ServiceUnavailableError(
                "Could not reach the payment provider. Please try again.",
                code="PAYMENT_PROVIDER_UNAVAILABLE",
            ) from exc
        return self._unwrap(response, path)

    async def _get(self, path: str) -> dict[str, Any]:
        try:
            async with self._client() as client:
                response = await client.get(path)
        except httpx.HTTPError as exc:
            logger.error("razorpay_request_failed", path=path, error=str(exc))
            raise ServiceUnavailableError(
                "Could not reach the payment provider. Please try again.",
                code="PAYMENT_PROVIDER_UNAVAILABLE",
            ) from exc
        return self._unwrap(response, path)

    @staticmethod
    def _unwrap(response: httpx.Response, path: str) -> dict[str, Any]:
        if response.status_code < 400:
            body: dict[str, Any] = response.json()
            return body

        try:
            error = response.json().get("error", {})
        except ValueError:
            error = {}
        description = error.get("description") or response.text[:300]
        code = error.get("code", "PROVIDER_ERROR")

        logger.warning(
            "razorpay_error",
            path=path,
            status_code=response.status_code,
            provider_code=code,
            description=description,
        )

        if response.status_code >= 500:
            raise ServiceUnavailableError(
                "The payment provider is temporarily unavailable.",
                code="PAYMENT_PROVIDER_UNAVAILABLE",
            )
        # A 4xx is our request being wrong — a bad amount, a duplicate
        # receipt, an uncapturable payment. Surfaced rather than retried.
        raise BusinessRuleError(
            f"Payment provider rejected the request: {description}",
            code="PAYMENT_PROVIDER_REJECTED",
            details={"provider_code": code},
        )
