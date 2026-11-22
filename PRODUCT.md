# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack
Next.js (App Router) with TypeScript, in `frontend/`. Chosen by the user for SEO and speed. Talks to the FastAPI backend in `backend/` over `/api/v1`.

## Users
- **Customers:** people in Indian metros (Mumbai, Bengaluru, Delhi, Goa) buying tickets for live music evenings, mostly on a phone, often under time pressure when popular events open. They sign in with Google.
- **Gate staff:** scan tickets on a phone at the venue, in low light, with a queue waiting. Sign in with Google; assigned to specific events.
- **Admins/organisers:** create events and ticket categories, manage bookings, refunds and staff. Admin screens are not part of the first frontend build.

## Product Purpose
JIVE Events is a single-company ticketing and event platform. A customer finds a night, picks tickets, pays through Razorpay and receives per-seat QR tickets. Success is a purchase that completes without confusion, and a gate scan that is fast and unambiguous.

## Positioning
One company's own events, sold directly: a quiet, editorial listening-room feel rather than a marketplace. Tickets are single-use, valid until the event ends, and a spent ticket stops showing its code.

## Operating Context
- Money is integer paise in the API; display as INR with Indian digit grouping.
- Inventory is held for a short, server-configured time while a customer pays. The frontend shows a countdown from the booking's expiry timestamp and never hard-codes the duration.
- Large sell-outs are expected (around 5,000 seats in minutes), so event pages and availability must stay fast under load.
- Payment: Razorpay checkout, then server-side signature verification. A payment can be pending, failed (hold still valid), or confirmed (tickets issued shortly after).
- QR codes are retrieved from the API per ticket; scanner results are one of SUCCESS, ALREADY_USED, WRONG_EVENT, CANCELLED, REFUNDED, INVALID, NOT_ASSIGNED, EXPIRED, with no override.

## Capabilities and Constraints
- Public: event listing and detail by slug, city filter, live availability.
- Customer: Google sign-in, phone number, create booking, checkout, verify, My bookings, My tickets, refund quote, cancel.
- Staff: assigned events, scan, attendance count.
- Limit of four tickets per person per event shown in the UI; the server is the authority.
- Undecided: cancellation-policy numbers, email/SMS provider, phone verification, real photography, final fonts, terms and privacy copy.

## Brand Commitments
- Name: JIVE. Black, white and grey only; serif headings in sentence case; white pill buttons; 24px-rounded photos; floating pill nav.
- Reference style supplied by the user: https://paris-afterhours.framer.website/events/deep-listening-night. Approved comps are in `design/`.
- No fabricated statistics, testimonials or capacity claims. No refund-timing or hold-time promises in copy.

## Evidence on Hand
- Approved static comps: `design/homepage.html`, `checkout.html`, `tickets.html`, `scanner.html`, `signin.html`, with shared `design/site.css`.
- Placeholder photography only (AI-generated in Stitch). No real photos, artist bios or venue assets yet.
- No real events, prices or counts beyond the sample data in the comps.

## Product Principles
1. Never lie to the customer about money or time: totals, holds and refund amounts come from the API.
2. Fast first paint on public pages; ship JavaScript only where a page is interactive.
3. One obvious next action on every screen.
4. Failure states are designed, not afterthoughts: payment failed, hold ended, sold out, limit reached.
5. The gate result must be readable at arm's length without reading.

## Accessibility & Inclusion
Target WCAG 2.2 AA. Scanner results use icon and words as well as colour. Respect reduced motion; the ticker must be pausable.
