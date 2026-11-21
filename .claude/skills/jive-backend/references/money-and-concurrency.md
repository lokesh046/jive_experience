# Money, inventory, payments and refunds

The four places this platform can lose real money. Read this before touching
any of them.

## Money

Integer paise everywhere: `BIGINT` in PostgreSQL, `int` in Python, minor units
on the wire. This is also what Razorpay and Cashfree expect, so nothing has to
be converted and nothing can drift.

```python
from app.core.money import rupees_to_paise, paise_to_rupees, percentage_of
```

- Never `float` for money. Not in a model, a schema, a calculation or a test.
- **The server calculates the price.** Read the ticket category price from the
  database at reservation time. A client-sent amount is only ever validated.
- Splitting an amount: compute the last part as `total - already_allocated`,
  never as a second independent percentage, or rounding can exceed the total
  by a paisa.

## Inventory — the core concurrency problem

Two people buying the last ticket at the same instant must not both succeed.

**Sizing target: a 5,000-seat event selling out in ~2 minutes** — see
`backend/docs/capacity.md` before changing anything in the reservation path.
At that rate a single inventory row per ticket category is adequate; the load
is in availability polling, not in writes.

Rules:

- PostgreSQL decides, inside a transaction. Redis never does.
- Use `SELECT ... FOR UPDATE` on the inventory row, or a conditional
  `UPDATE ... WHERE available >= :qty` and check the affected row count.
- A CHECK constraint must make negative stock impossible regardless.
- Reservations expire (10 minutes). Expiry is a background job **and** a
  guard at every read — never assume the sweeper has run.
- Enforce the per-booking purchase limit server-side.

The hard case, which must be handled explicitly: **payment succeeds after the
reservation expired.** Re-check availability; if stock can still be allocated,
confirm the booking; if not, start an automatic refund and tell the customer.
Never silently keep the money, and never confirm a booking you cannot seat.

## Payments

- Create the order server-side; use the provider's hosted checkout.
- Confirm server-side against the gateway. A browser redirect saying "success"
  is not proof of anything.
- Verify every webhook signature before reading the body.
- Deduplicate: store the gateway event id with a UNIQUE constraint and ignore
  repeats. Webhooks arrive more than once — that is normal, not an error.
- Use idempotency keys on every write to the gateway.
- Never store raw card details. Never log a full gateway payload containing
  customer payment data.
- Tickets are issued only after a payment is confirmed server-side.

## Refunds

- Eligibility comes from the event's own cancellation policy, validated
  server-side, and shown to the customer before purchase.
- **A gateway accepting a refund request does not mean it is done.** Model it
  as `REQUESTED → PROCESSING → SUCCEEDED | FAILED` and reconcile on a
  schedule.
- Every refund call carries a unique idempotency reference, so a retry cannot
  refund twice.
- Invalidate the tickets when a refund succeeds — not when it is requested.
- Refunded total can never exceed the captured total; enforce it in the
  database.
- Record who initiated it and why in `audit_logs`.

## QR tickets and check-in

- One ticket, and one QR token, **per attendee** — 4 tickets means 4 distinct
  QRs.
- Token: cryptographically random, stored hashed, with no personal data inside
  the QR itself.
- Check-in is atomic and one-time: a conditional UPDATE that flips the status
  only if it is currently unused, then check the row count. Two simultaneous
  scans of the same ticket must produce exactly one success.
- Distinguish the failures for the scanner UI: valid, already used, wrong
  event, cancelled, refunded, invalid QR, staff not assigned to this event.
- Record ticket id, event id, staff id, timestamp and result for every scan —
  including the failures.
- Online only in v1. No offline acceptance.

## Background jobs

Anything with an external side effect (email, SMS, gateway call) goes through
a durable PostgreSQL outbox, not a fire-and-forget task. Every job must be
idempotent and safe to retry — assume it will run twice.
