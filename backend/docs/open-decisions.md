# Open decisions and required credentials

Tracked here because each one blocks a specific phase. Nothing below can be
invented by the development team — all of it is a business decision or a
client-owned account.

## Blocking decisions

### 1. Payment gateway — Razorpay or Cashfree? (blocks Phase 4)

One provider, not both. The choice changes the payment and refund table shapes,
the webhook verification code and the refund state machine, so it should be
settled before the Phase 4 schema is written.

Either is workable. What is needed to decide: which merchant account can
complete KYC soonest, and the negotiated transaction rate.

### 2. Partial refunds in v1? (blocks Phase 5)

The master brief asks for partial refunds "where the event policy permits". The
14-day MVP checklist explicitly excludes "complex partial refunds".

Recommendation: **full refunds only in v1**, with the schema built to support
per-booking-item partial refunds later (refund rows already reference booking
items). Partial refunds multiply the reconciliation cases and are the single
most expensive thing on the list relative to how often they are used.

### 3. Cancellation and refund policy (blocks Phase 5)

Required as concrete numbers, because this becomes code and is shown to the
customer before purchase:

- Cutoff windows and the refund percentage in each (e.g. 100% up to 7 days
  before, 50% up to 48 hours before, 0% after).
- Whether the payment gateway fee is retained or refunded.
- Whether a customer may cancel part of a booking or only the whole booking.
- What happens when the company cancels an event (presumably 100%, including
  any fee).

### 4. Timeline (affects all phases)

The proposal says 5–8 weeks; a separate document specifies a 14-day MVP. The
full deliverable list is not achievable in 14 days. If 14 days is firm, the
scope has to be cut explicitly — the honest minimum is: public site, event
listing/detail, OTP login, booking + payment, QR tickets, staff scanner, and a
thin admin. Services/artists/portfolio/reporting would follow after launch.

## Required credentials and accounts

Listed in the order they are needed. None are required to continue building
today — each blocks the integration work for its phase.

| # | Needed for | Item |
|---|---|---|
| 1 | Phase 2 | Google Cloud OAuth 2.0 Web client: client ID, client secret, and the exact redirect URI(s) registered |
| 2 | Phase 4 | Payment gateway sandbox keys (key id, secret, webhook secret) |
| 3 | Phase 4 | KYC-completed merchant account with the refunds API enabled, and the settlement bank account |
| 4 | Phase 6 | Transactional email: SMTP credentials and a verified sender domain (SPF/DKIM) |
| 5 | Phase 7 | Ubuntu VPS with root/sudo SSH access |
| 6 | Phase 7 | Domain and DNS control |
| 7 | Phase 7 | Off-server backup destination (S3-compatible bucket + credentials) |
| 8 | Phase 7 | Object storage for event images, or confirmation to serve them from the VPS disk |

## Required content

Clearly-marked placeholders are used until each is supplied. No company
details, client names, testimonials or event history will be invented.

- Logo, brand colours and typography.
- Homepage, About and Services copy.
- Privacy Policy, Terms & Conditions, Cancellation/Refund Policy, grievance
  contact. These are legal documents and must be supplied or approved by the
  client, not drafted by the development team.
- Real event data, artist profiles and portfolio media, with the rights to
  publish each photograph, artist name and piece of artwork.
- The destination for enquiry notifications (email address or inbox).

## Capacity note

A single VPS is not a high-availability deployment. A popular ticket release
concentrates traffic into a few minutes against one database. Before any such
release, agree:

- expected peak concurrent buyers;
- whether a queue or staggered sale window is acceptable;
- the rollback plan if the server saturates.

This is documented properly in Phase 7, but the constraint exists from day one
and the booking design in Phase 4 depends on the answer.
