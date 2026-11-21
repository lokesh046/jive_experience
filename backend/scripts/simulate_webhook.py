#!/usr/bin/env python
"""Send a correctly signed Razorpay webhook to a local API.

Razorpay cannot reach `localhost`, which normally means a tunnel. But the
signature is just HMAC-SHA256 of the raw body keyed with the webhook secret —
a value *you* choose in the dashboard. So locally you can set any secret in
`.env` and sign the request yourself. The backend cannot tell the difference,
which is exactly the point: it exercises the real verification path.

    python -m scripts.simulate_webhook --payment pay_X --order order_X --amount 300000
    python -m scripts.simulate_webhook --event payment.failed  --payment pay_X
    python -m scripts.simulate_webhook --event refund.processed --payment pay_X

Use `--duplicate` to send the same event twice and watch it deduplicate.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import sys
import time
import uuid

import httpx

from app.core.config import get_settings

EVENTS = ("payment.captured", "payment.failed", "refund.processed", "refund.failed")


def build_payload(*, event: str, payment_id: str, order_id: str, amount_paise: int) -> dict:
    """A payload shaped like Razorpay's own."""
    status = {
        "payment.captured": "captured",
        "payment.failed": "failed",
        "refund.processed": "captured",
        "refund.failed": "captured",
    }[event]

    entity = {
        "id": payment_id,
        "entity": "payment",
        "amount": amount_paise,
        "currency": "INR",
        "status": status,
        "order_id": order_id,
        "method": "upi",
        "captured": status == "captured",
        "created_at": int(time.time()),
    }
    if event == "payment.failed":
        entity["error_code"] = "BAD_REQUEST_ERROR"
        entity["error_description"] = "Payment was declined by the bank"

    return {
        "entity": "event",
        "account_id": "acc_simulated",
        "event": event,
        "contains": ["payment"],
        "payload": {"payment": {"entity": entity}},
        "created_at": int(time.time()),
    }


def send(url: str, payload: dict, secret: str, event_id: str) -> httpx.Response:
    # Sign the exact bytes that are sent. Re-serialising would change
    # whitespace and key order, and the signature would no longer match —
    # which is the single most common way this integration is got wrong.
    body = json.dumps(payload).encode()
    signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    return httpx.post(
        url,
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Razorpay-Signature": signature,
            "X-Razorpay-Event-Id": event_id,
        },
        timeout=30.0,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://localhost:8001/api/v1/payments/webhook")
    parser.add_argument("--event", default="payment.captured", choices=EVENTS)
    parser.add_argument("--payment", required=True, help="Razorpay payment id")
    parser.add_argument("--order", default="", help="Razorpay order id")
    parser.add_argument("--amount", type=int, default=0, help="Amount in paise")
    parser.add_argument(
        "--duplicate",
        action="store_true",
        help="Send the same event twice — the second must be ignored",
    )
    parser.add_argument(
        "--tamper",
        action="store_true",
        help="Alter the body after signing — must be rejected",
    )
    args = parser.parse_args()

    settings = get_settings()
    if not settings.payment_webhook_secret:
        print(
            "PAYMENT_WEBHOOK_SECRET is not set.\n"
            "Set any value in .env for local testing; replace it with the one "
            "from the Razorpay dashboard when you create the real webhook.",
            file=sys.stderr,
        )
        return 1
    secret = settings.payment_webhook_secret.get_secret_value()

    payload = build_payload(
        event=args.event,
        payment_id=args.payment,
        order_id=args.order,
        amount_paise=args.amount,
    )
    event_id = f"evt_{uuid.uuid4().hex[:16]}"

    if args.tamper:
        body = json.dumps(payload).encode()
        signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        response = httpx.post(
            args.url,
            content=body.replace(b'"amount"', b'"amoutn"'),
            headers={
                "Content-Type": "application/json",
                "X-Razorpay-Signature": signature,
                "X-Razorpay-Event-Id": event_id,
            },
            timeout=30.0,
        )
        print(f"tampered body  -> {response.status_code} {response.text[:160]}")
        return 0 if response.status_code == 401 else 1

    response = send(args.url, payload, secret, event_id)
    print(f"{args.event:18} -> {response.status_code} {response.text[:160]}")

    if args.duplicate:
        again = send(args.url, payload, secret, event_id)
        print(f"{'redelivered':18} -> {again.status_code} {again.text[:160]}")

    return 0 if response.status_code < 400 else 1


if __name__ == "__main__":
    raise SystemExit(main())
