# Bot and scalper controls

A 5,000-seat event selling out in two minutes is exactly the profile automated
buyers target. See `capacity.md` for the load numbers this sits alongside.

**Goal: make a scalper's cost per ticket exceed their margin.** Not to make
automation impossible — that is not achievable, and designing as though it
were leads to controls that block real customers instead.

## Identity: Google OAuth, and why the phone still matters

**Changed 2026-11-20: customer sign-in is Google OAuth 2.0, not phone OTP.**

This weakens the strongest control that was in this plan. A Google account is
free and takes a minute to create, so "one account per person" is no longer
something sign-in enforces by itself. A reseller can hold fifty.

What remains, and what has to carry the weight instead:

1. **A verified phone number before reservation.** The number is collected
   after sign-in (`PUT /api/v1/auth/phone`) and is UNIQUE in the database, so
   one number means one account. **Phase 4 must require a verified number
   before a reservation is created** — storing an unverified string buys
   nothing, because a reseller will type any digits.
2. Verification needs an SMS provider. That is a cost and a decision that is
   still open; without it, the per-account limit is advisory.
3. Google's `email_verified` claim is required at sign-in, so throwaway
   addresses that Google itself has not verified are refused.

**Requirement: sign-in must happen before reservation, not at checkout.** If
inventory can be held by an unidentified session, no per-account limit can be
enforced at all.

## Layer 1 — Per-account purchase limits (highest value)

- Maximum tickets **per customer account, per event**.
- Counted across **all** of that customer's bookings for the event, not per
  booking. Counting per booking is trivially bypassed by booking twice.
- Admin-configurable per event. **Recommended default: 4.**
- Enforced in the booking service and backed by a database constraint, so an
  application bug cannot let it through.

## Layer 2 — Turnstile

Two placements:

1. OTP request — protects the SMS spend.
2. Reservation create — protects inventory.

A free tier exists; confirm current terms and limits before committing.

## Layer 3 — Rate limits keyed to the account

**Important: the backend does not send the OTP.** With Firebase Phone Auth the
SMS is requested by the client SDK and sent by Google. The backend only
verifies the resulting ID token. So SMS-send abuse is controlled in the
Firebase console, not in our code:

| Control | Where |
|---|---|
| reCAPTCHA on OTP request | Firebase phone auth (built in on web) |
| App Check | Firebase console — blocks requests from non-genuine apps |
| SMS region policy (+91 only) | Firebase console |
| SMS quota alerts | Firebase/GCP billing |

What the backend *can* limit is the token-exchange endpoint, which is what
creates accounts and sessions:

| Endpoint | Limit | Fails |
|---|---|---|
| `POST /auth/otp` (token exchange) | per IP, and per phone once verified | closed |
| `POST /auth/admin/login` | per IP and per email | closed |
| `POST /auth/refresh` | per IP | closed |
| Reservation create (Phase 4) | ~5 per minute per authenticated user | open |

## Layer 4 — Detection after the fact

Log enough to investigate: IP, user agent, request timing relative to sale
open, account age. Flag many accounts from one IP range, reservations within
milliseconds of the drop, and sequential phone numbers.

Admins must be able to cancel and refund flagged bookings **before** the
event. Audit every such action.

## Two traps specific to this market

**Never rate-limit by IP alone.** Indian mobile carriers put very large numbers
of users behind CGNAT, so thousands of genuine customers share an IP. An
aggressive per-IP limit will reject real buyers during the drop and will look
indistinguishable from an outage. Treat IP as a signal, and challenge rather
than block.

**SMS pumping.** Attackers trigger OTPs toward premium-rate numbers and take a
share of the revenue; Firebase phone auth is a repeated target. It does not
steal tickets — it drains the SMS budget. If the business sells only in India,
**restrict OTP to +91 numbers in the Firebase configuration.** This removes
most of the exposure at no cost.

## Client decisions required

Policy beats engineering here. None of these can be decided by the development
team:

1. **Ticket limit per person per event** — 2, 4 or 6. Lower is fairer and
   reduces scalping; it also reduces revenue per transaction.
2. **Named tickets with ID check at entry?** The QR ticket can carry the
   attendee name. If a ticket is worthless to a resale buyer, scalping stops
   being profitable — this is the control that actually ends it. Cost: slower
   entry and more staff.
3. **Transfers** — currently out of scope, which helps. Confirm it stays that
   way.
4. **Staggered release** — selling in two waves halves both the spike and the
   scalper incentive.

## Build order

| Phase | Work |
|---|---|
| 2 (auth) | OTP rate limits per phone and per IP, +91 restriction, Turnstile on OTP request |
| 4 (booking) | Per-account per-event limit, Turnstile on reservation, per-user reservation limits |
| 6 (ops) | Admin view of flagged bookings, bulk cancel and refund |

## Honest limitation

CAPTCHA-solving services are cheap and effective, so Turnstile raises cost
without eliminating automation. Phone verification plus a low per-account cap
plus named entry is what removes the profit. Any plan that relies on CAPTCHA
alone will fail against a motivated reseller.
