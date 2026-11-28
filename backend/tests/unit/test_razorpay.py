"""Razorpay adapter.

Every request is served by an `httpx.MockTransport`, so these tests make no
network calls and need no credentials. What they pin down is the part that
cannot be checked by reading: the two different signatures, the state mapping,
and the shape of what we send.
"""

from __future__ import annotations

import hashlib
import hmac
import json

import httpx
import pytest

from app.core.config import Settings
from app.core.errors import (
    AuthenticationError,
    BusinessRuleError,
    ServiceUnavailableError,
)
from app.services.payment_provider import ProviderPaymentState
from app.services.providers.razorpay import RazorpayProvider

KEY_ID = "rzp_test_ABCDEF1234567"
KEY_SECRET = "test-key-secret"
WEBHOOK_SECRET = "test-webhook-secret"


def provider(handler) -> RazorpayProvider:
    settings = Settings(
        payment_provider="razorpay",
        payment_key_id=KEY_ID,
        payment_key_secret=KEY_SECRET,
        payment_webhook_secret=WEBHOOK_SECRET,
    )
    return RazorpayProvider(settings, transport=httpx.MockTransport(handler))


def json_response(payload: dict, status: int = 200):
    def handler(request: httpx.Request) -> httpx.Response:
        handler.request = request  # type: ignore[attr-defined]
        return httpx.Response(status, json=payload)

    return handler


# ------------------------------------------------------------- test mode ---


def test_test_keys_are_recognised() -> None:
    assert provider(json_response({})).is_test_mode


def test_live_keys_are_recognised() -> None:
    settings = Settings(
        payment_provider="razorpay",
        payment_key_id="rzp_live_ABCDEF1234567",
        payment_key_secret=KEY_SECRET,
    )
    assert not RazorpayProvider(settings).is_test_mode


def test_missing_credentials_refuse_to_construct() -> None:
    """Better to fail at start-up than to fail mid-checkout."""
    with pytest.raises(RuntimeError, match="PAYMENT_KEY_ID"):
        RazorpayProvider(Settings(payment_provider="razorpay"))


# ---------------------------------------------------------------- orders ---


async def test_create_order_sends_paise_and_the_booking_reference() -> None:
    handler = json_response(
        {
            "id": "order_ABC123",
            "amount": 350000,
            "currency": "INR",
            "receipt": "JIVE-7F3K2A4B",
            "status": "created",
        },
        status=200,
    )
    order = await provider(handler).create_order(
        amount_paise=350000,
        currency="INR",
        reference="JIVE-7F3K2A4B",
        idempotency_key="order:abc",
    )

    sent = json.loads(handler.request.content)  # type: ignore[attr-defined]
    assert sent["amount"] == 350000, "amount must be paise, not rupees"
    assert sent["currency"] == "INR"
    # Razorpay treats `receipt` as its own dedupe key.
    assert sent["receipt"] == "JIVE-7F3K2A4B"
    assert sent["notes"]["booking_reference"] == "JIVE-7F3K2A4B"

    assert order.provider_order_id == "order_ABC123"
    assert order.amount_paise == 350000


async def test_checkout_payload_carries_the_key_id_but_never_the_secret() -> None:
    """The publishable key id reaches the browser; the secret must not."""
    handler = json_response(
        {"id": "order_ABC123", "amount": 100000, "currency": "INR", "receipt": "r"}
    )
    order = await provider(handler).create_order(
        amount_paise=100000, currency="INR", reference="JIVE-1", idempotency_key="k"
    )

    assert order.checkout_payload["key"] == KEY_ID
    assert KEY_SECRET not in json.dumps(order.checkout_payload)


def test_a_reopened_order_gets_the_same_checkout_fields_as_a_new_one() -> None:
    """Closing the payment sheet and opening it again must still have the key and order."""
    payload = provider(json_response({})).checkout_payload_for(
        order_id="order_ABC123", amount_paise=150000, currency="INR", receipt="JIVE-1"
    )

    assert payload["key"] == KEY_ID
    assert payload["order_id"] == "order_ABC123"
    assert payload["amount"] == 150000
    assert KEY_SECRET not in json.dumps(payload)


async def test_amount_below_the_provider_minimum_is_refused_locally() -> None:
    """Rejected before the network call — Razorpay's floor is 100 paise."""
    with pytest.raises(BusinessRuleError, match="minimum"):
        await provider(json_response({})).create_order(
            amount_paise=50, currency="INR", reference="JIVE-1", idempotency_key="k"
        )


async def test_long_reference_is_truncated_to_the_receipt_limit() -> None:
    handler = json_response({"id": "order_X", "amount": 100000, "currency": "INR", "receipt": "x"})
    await provider(handler).create_order(
        amount_paise=100000,
        currency="INR",
        reference="J" * 80,
        idempotency_key="k",
    )
    sent = json.loads(handler.request.content)  # type: ignore[attr-defined]
    assert len(sent["receipt"]) <= 40


async def test_provider_rejection_surfaces_as_a_business_rule_error() -> None:
    handler = json_response(
        {
            "error": {
                "code": "BAD_REQUEST_ERROR",
                "description": "Duplicate request. This request has already been processed.",
            }
        },
        status=400,
    )
    with pytest.raises(BusinessRuleError) as excinfo:
        await provider(handler).create_order(
            amount_paise=100000, currency="INR", reference="JIVE-1", idempotency_key="k"
        )
    assert excinfo.value.code == "PAYMENT_PROVIDER_REJECTED"


async def test_provider_outage_is_not_the_callers_fault() -> None:
    """A 5xx is 503, not 4xx: the request was fine, the provider was not."""
    with pytest.raises(ServiceUnavailableError):
        await provider(json_response({}, status=502)).create_order(
            amount_paise=100000, currency="INR", reference="JIVE-1", idempotency_key="k"
        )


# -------------------------------------------------------------- payments ---


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("captured", ProviderPaymentState.SUCCEEDED),
        ("refunded", ProviderPaymentState.SUCCEEDED),
        ("authorized", ProviderPaymentState.PENDING),
        ("created", ProviderPaymentState.PENDING),
        ("failed", ProviderPaymentState.FAILED),
        ("cancelled", ProviderPaymentState.FAILED),
    ],
)
async def test_payment_status_mapping(status: str, expected: ProviderPaymentState) -> None:
    """`authorized` is the one that matters: money held, not taken.

    Mapping it to failure would refund a customer whose payment is about to
    capture correctly.
    """
    handler = json_response(
        {
            "id": "pay_ABC",
            "order_id": "order_ABC",
            "amount": 350000,
            "currency": "INR",
            "status": status,
            "method": "upi",
        }
    )
    payment = await provider(handler).fetch_payment("pay_ABC")
    assert payment.state is expected


async def test_unknown_status_is_treated_as_pending_never_success() -> None:
    """A state we do not understand must not confirm a booking."""
    handler = json_response(
        {"id": "pay_X", "amount": 1000, "currency": "INR", "status": "some_new_state"}
    )
    payment = await provider(handler).fetch_payment("pay_X")
    assert payment.state is ProviderPaymentState.PENDING
    assert not payment.succeeded


async def test_failure_reason_is_captured() -> None:
    handler = json_response(
        {
            "id": "pay_X",
            "amount": 1000,
            "currency": "INR",
            "status": "failed",
            "error_description": "Payment was declined by the bank",
        }
    )
    payment = await provider(handler).fetch_payment("pay_X")
    assert payment.failed
    assert "declined" in (payment.failure_reason or "")


# ----------------------------------------------------- checkout signature ---


def test_valid_checkout_signature_is_accepted() -> None:
    order_id, payment_id = "order_ABC", "pay_XYZ"
    signature = hmac.new(
        KEY_SECRET.encode(), f"{order_id}|{payment_id}".encode(), hashlib.sha256
    ).hexdigest()

    assert provider(json_response({})).verify_checkout_signature(
        provider_order_id=order_id,
        provider_payment_id=payment_id,
        signature=signature,
    )


def test_checkout_signature_is_signed_with_the_api_secret_not_the_webhook_secret() -> None:
    """The two secrets are different; using the wrong one must not validate."""
    order_id, payment_id = "order_ABC", "pay_XYZ"
    wrong = hmac.new(
        WEBHOOK_SECRET.encode(), f"{order_id}|{payment_id}".encode(), hashlib.sha256
    ).hexdigest()

    assert not provider(json_response({})).verify_checkout_signature(
        provider_order_id=order_id, provider_payment_id=payment_id, signature=wrong
    )


def test_tampered_payment_id_fails_the_checkout_signature() -> None:
    """Swapping in someone else's payment id is the attack this stops."""
    signature = hmac.new(KEY_SECRET.encode(), b"order_ABC|pay_XYZ", hashlib.sha256).hexdigest()

    assert not provider(json_response({})).verify_checkout_signature(
        provider_order_id="order_ABC",
        provider_payment_id="pay_SOMEONE_ELSE",
        signature=signature,
    )


# ------------------------------------------------------ webhook signature ---


def signed_webhook(payload: dict, secret: str = WEBHOOK_SECRET) -> tuple[bytes, dict]:
    body = json.dumps(payload).encode()
    signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return body, {
        "x-razorpay-signature": signature,
        "x-razorpay-event-id": "evt_12345",
    }


CAPTURED = {
    "event": "payment.captured",
    "payload": {
        "payment": {
            "entity": {
                "id": "pay_ABC",
                "order_id": "order_ABC",
                "amount": 350000,
                "currency": "INR",
                "status": "captured",
            }
        }
    },
}


def test_valid_webhook_is_parsed() -> None:
    body, headers = signed_webhook(CAPTURED)
    envelope = provider(json_response({})).parse_webhook(body=body, headers=headers)

    assert envelope.event_type == "payment.captured"
    assert envelope.provider_payment_id == "pay_ABC"
    assert envelope.provider_order_id == "order_ABC"
    assert envelope.amount_paise == 350000
    assert envelope.succeeded


def test_webhook_event_id_comes_from_the_header() -> None:
    """Razorpay's per-delivery id is what makes a retry deduplicate."""
    body, headers = signed_webhook(CAPTURED)
    envelope = provider(json_response({})).parse_webhook(body=body, headers=headers)
    assert envelope.provider_event_id == "evt_12345"


def test_webhook_with_a_forged_signature_is_refused() -> None:
    """An unsigned webhook is an attacker claiming a payment succeeded."""
    body, headers = signed_webhook(CAPTURED, secret="not-the-webhook-secret")

    with pytest.raises(AuthenticationError) as excinfo:
        provider(json_response({})).parse_webhook(body=body, headers=headers)
    assert excinfo.value.code == "WEBHOOK_SIGNATURE_INVALID"


def test_webhook_body_tampering_is_detected() -> None:
    """The signature covers the raw bytes, so changing the amount breaks it."""
    body, headers = signed_webhook(CAPTURED)
    tampered = body.replace(b'"amount": 350000', b'"amount": 1')

    with pytest.raises(AuthenticationError):
        provider(json_response({})).parse_webhook(body=tampered, headers=headers)


def test_webhook_without_a_signature_header_is_refused() -> None:
    body, _ = signed_webhook(CAPTURED)
    with pytest.raises(AuthenticationError) as excinfo:
        provider(json_response({})).parse_webhook(body=body, headers={})
    assert excinfo.value.code == "WEBHOOK_SIGNATURE_MISSING"


def test_webhook_without_a_configured_secret_refuses_rather_than_accepts() -> None:
    settings = Settings(
        payment_provider="razorpay",
        payment_key_id=KEY_ID,
        payment_key_secret=KEY_SECRET,
        payment_webhook_secret=None,
    )
    unconfigured = RazorpayProvider(settings)
    body, headers = signed_webhook(CAPTURED)

    with pytest.raises(ServiceUnavailableError):
        unconfigured.parse_webhook(body=body, headers=headers)


def test_failed_payment_webhook_is_not_a_success() -> None:
    failed = json.loads(json.dumps(CAPTURED))
    failed["event"] = "payment.failed"
    failed["payload"]["payment"]["entity"]["status"] = "failed"
    body, headers = signed_webhook(failed)

    envelope = provider(json_response({})).parse_webhook(body=body, headers=headers)
    assert not envelope.succeeded
    assert envelope.state is ProviderPaymentState.FAILED


# --------------------------------------------------------------- refunds ---


async def test_refund_sends_the_razorpay_specific_idempotency_header() -> None:
    """`X-Refund-Idempotency`, not the generic `Idempotency-Key`."""
    handler = json_response({"id": "rfnd_ABC", "amount": 350000, "status": "processed"})
    result = await provider(handler).refund(
        provider_payment_id="pay_ABC",
        amount_paise=350000,
        idempotency_key="refund:0c8f-4a2b:350000",
    )

    headers = handler.request.headers  # type: ignore[attr-defined]
    assert "x-refund-idempotency" in headers
    key = headers["x-refund-idempotency"]
    # Razorpay allows only alphanumerics, hyphen and underscore.
    assert ":" not in key
    assert len(key) >= 10

    assert result.provider_refund_id == "rfnd_ABC"
    assert result.completed


async def test_pending_refund_is_not_reported_complete() -> None:
    """The bank has not settled it. Treating this as done would mark a booking
    refunded before the customer has their money."""
    handler = json_response({"id": "rfnd_X", "amount": 1000, "status": "pending"})
    result = await provider(handler).refund(
        provider_payment_id="pay_X", amount_paise=1000, idempotency_key="refund-abc-123"
    )
    assert not result.completed
    assert result.status == "pending"


async def test_failed_refund_carries_its_reason() -> None:
    handler = json_response(
        {
            "id": "rfnd_X",
            "amount": 1000,
            "status": "failed",
            "error_description": "Insufficient merchant balance",
        }
    )
    result = await provider(handler).refund(
        provider_payment_id="pay_X", amount_paise=1000, idempotency_key="refund-abc-123"
    )
    assert not result.completed
    assert "balance" in (result.failure_reason or "")


def test_idempotency_keys_are_deterministic() -> None:
    """The same logical refund must always produce the same key, or a retry
    would create a second refund."""
    adapter = provider(json_response({}))
    first = adapter._idempotency_key("refund:abc:100")
    second = adapter._idempotency_key("refund:abc:100")
    assert first == second
