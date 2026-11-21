# Razorpay setup (test mode)

What the backend needs: a **key id**, a **key secret**, and a **webhook
secret**. Nothing else — no SDK, no code changes.

The adapter is `app/services/providers/razorpay.py`. Everything above it talks
to the provider-independent contract in `app/services/payment_provider.py`, so
swapping providers later touches one file.

---

## 1. Get test keys

1. <https://dashboard.razorpay.com> → make sure the toggle says **Test Mode**.
2. **Account & Settings → API Keys → Generate Test Key**.
3. Copy both values. The secret is shown **once**; if you lose it, regenerate.

Test keys are prefixed `rzp_test_`. Live keys are `rzp_live_`. The backend
reports which it is using through `RazorpayProvider.is_test_mode`, and there
is a test asserting the two are distinguished — a live key reaching a staging
environment is the expensive mistake here.

## 2. Turn on automatic capture

**Settings → Payments → Payment Capture → Capture payments automatically.**

Without it a payment stops at `authorized`: the money is held but never
taken, and Razorpay auto-refunds it after a few days. The backend handles that
state correctly — it records the payment as AUTHORIZED, confirms nothing, and
lets reconciliation ask again — but the sale never completes.

This setting only applies when the server uses the Orders API, which this
backend does.

## 3. Configure the webhook

**Settings → Webhooks → Add New Webhook**

| Field | Value |
|---|---|
| Webhook URL | `https://your-domain.com/api/v1/payments/webhook` |
| Secret | generate a long random string, keep it |
| Active events | `payment.captured`, `payment.failed`, `refund.processed`, `refund.failed` |

The webhook secret is **not** the API key secret. They sign different things:

| Signature | Covers | Signed with |
|---|---|---|
| `X-Razorpay-Signature` on a webhook | the raw request body | the **webhook secret** |
| `razorpay_signature` from Checkout.js | `order_id\|payment_id` | the **API key secret** |

Both are verified, each with the right secret.

**Local testing** needs a public URL — Razorpay cannot reach `localhost`. Use
a tunnel (ngrok, zrok, cloudflared) and point the webhook at it.

### Working without a webhook secret

Leaving `PAYMENT_WEBHOOK_SECRET` unset is a supported state, not a broken one.
Checkout, verification, refunds and reconciliation all work; only the webhook
endpoint refuses, with `WEBHOOK_SECRET_NOT_CONFIGURED`.

That is enough to develop and test against, because
`POST /bookings/{ref}/verify` asks Razorpay directly and is authoritative. The
webhook is the *backstop* for the case the browser never comes back — the
customer closing the tab after paying, or losing signal. Without it, those
payments are caught by the reconciliation sweep instead, which runs in the
worker and asks Razorpay about anything still in flight.

**Do not put a placeholder in that variable.** A wrong secret fails signature
verification on every delivery, which looks like an attack in the logs rather
than a configuration mistake. Unset is honest; wrong is confusing.

## 4. Configure the backend

```bash
PAYMENT_PROVIDER=razorpay
PAYMENT_KEY_ID=rzp_test_xxxxxxxxxxxxx
PAYMENT_KEY_SECRET=xxxxxxxxxxxxxxxxxxxxxxxx     # (SECRET)
PAYMENT_WEBHOOK_SECRET=xxxxxxxxxxxxxxxxxxxx     # (SECRET)
```

Restart the API and the worker. With `PAYMENT_PROVIDER` unset, checkout and
refunds refuse with `PAYMENT_PROVIDER_NOT_CONFIGURED` rather than pretending
to succeed.

## 5. Test cards

Any future expiry date and any CVV.

| Type | Number |
|---|---|
| Visa (domestic) | `4111 1111 1111 1111` |
| Mastercard | `5267 3181 8797 5449` |
| Visa (international) | `4012 8888 8888 1881` |

UPI: `success@razorpay` succeeds, `failure@razorpay` fails.
Netbanking and wallets show a mock page with success and failure buttons.

Razorpay publishes current test instruments at
<https://razorpay.com/docs/payments/payments/test-card-details/> — check there
rather than trusting this table, since the numbers change.

---

## How the flow runs

```
POST /bookings                    hold inventory, pending booking
POST /bookings/{ref}/checkout     → Razorpay order; returns checkout_payload
   client opens Checkout.js with that payload
POST /bookings/{ref}/verify       { provider_payment_id, provider_order_id, signature }
   ── signature checked, then Razorpay asked directly ──
   booking CONFIRMED, outbox issues one QR ticket per seat
```

The webhook arrives independently and goes through the same confirmation
path. Whichever gets there first confirms; the other is a no-op. Neither is
trusted on its own: the browser's return is only a hint, and a webhook is
accepted only if its signature verifies.

## What is deliberate

**`receipt` carries the booking reference.** Razorpay treats it as a dedupe
key and rejects a second order with the same one, so a retried checkout cannot
create a second charge.

**Refunds use `X-Refund-Idempotency`** — Razorpay's refund-specific header,
not the generic `Idempotency-Key`. It allows only alphanumerics, hyphen and
underscore, so our internal keys are transformed deterministically: the same
logical refund always produces the same header value, which is what makes the
worker's retries safe.

**A refund is not complete when Razorpay accepts it.** Razorpay returns
`pending` until the bank settles, which can take days. Nothing marks a booking
refunded or invalidates a ticket until the status reaches `processed`.

**An unknown payment status is treated as pending, never success.** If
Razorpay introduces a state this adapter has not seen, reconciliation asks
again instead of confirming a booking against a payment we do not understand.

## Before going live

- [ ] Complete KYC; the account must be activated for live payments
- [ ] Generate **live** keys; confirm the key id starts `rzp_live_`
- [ ] Re-create the webhook against the production URL, with a new secret
- [ ] Automatic capture enabled in **live** mode (it is a separate setting)
- [ ] Settlement bank account verified
- [ ] One real low-value end-to-end payment, then refund it
