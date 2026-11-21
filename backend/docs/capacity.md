# Capacity target

**Agreed target (2026-11-20): a 5,000-seat event that sells out in ~2 minutes.**

Everything below is sized against that number. If the target changes — a
larger venue, or a faster sellout — this document and the Phase 4 inventory
design must be revisited before building.

## Load profile

| Metric | Value |
|---|---|
| Tickets | 5,000 in ~120 s → **~42 tickets/sec** |
| Bookings (at ~2.5 tickets each) | **~17 bookings/sec** average |
| Front-loaded peak (first 30 s) | **~40 bookings/sec** |
| Expected oversubscription | 4–10× → **15,000–20,000 people at t=0** |
| Availability polling (3 s interval) | **~5,000 req/sec** |

These are estimates. They are not confirmed until the load test below runs.

## Where the load actually is

The write path is not the bottleneck. One PostgreSQL row handles roughly
500–1,000 short transactions/sec; the target needs ~40. That is ~12× headroom,
so **a single inventory row per ticket category is adequate** — no sharded
counters, no pre-minted slot table. Keep the schema simple.

The pressure comes from the ~15,000 people who do *not* get a ticket: page
loads and availability polling outnumber actual sales by roughly 100:1. All of
it is cacheable and none of it should reach PostgreSQL.

## Required design (Phase 4)

1. **Edge-cache the public event page** (CDN). The biggest single win.
2. **Cache the availability endpoint for 1–3 s** in Redis. Stale-by-seconds is
   fine; the authoritative check happens inside the reservation transaction.
3. **Fast-fail before locking.** Check cached availability and reject sold-out
   attempts immediately. Set a short `lock_timeout` so a contended request
   fails in milliseconds instead of queueing.
4. **Minimal reservation transaction.** A single conditional
   `UPDATE ... WHERE available >= :qty RETURNING`. No gateway call, no email,
   no other work inside the lock. Payment happens after the lock is released.
5. **pgBouncer** in front of PostgreSQL so a spike cannot exhaust connections.
6. **Reservation expiry of 5 minutes**, not 10, with the sweeper running every
   15–30 s. At a 2-minute sellout, seats held by non-payers are the scarcest
   resource in the system.

## Abuse and fairness

A 2-minute sellout attracts automated buyers. These matter more than hardware:

- CAPTCHA/Turnstile on the booking flow.
- Purchase limits enforced **per customer account**, not only per IP — one
  person with twenty tabs is the common case.
- Rate limit the reservation endpoint per authenticated user.

## Waiting room

Optional at this scale if the caching above is done properly. Revisit if the
first real drop shows queueing. Two options:

- Cloudflare Waiting Room — paid feature; confirm current plan tier and
  pricing before committing.
- Redis-based queue built in-house — roughly 1–2 days, no recurring cost.

Default: do not build it up front. Measure the first drop, then decide.

## Infrastructure

₹50,000/year is workable **provided the CDN absorbs the static and polling
load**. Preferred shape:

- Two hosts: API + Redis on one, PostgreSQL on its own. Safer under a drop.
- Acceptable fallback: one 4–8 vCPU / 16 GB host running everything.

Provider pricing to be confirmed against live quotes, not estimated.

## Mandatory before the first real sale

**A load test is a Phase 4 deliverable, not a launch-night activity.**

Simulate with k6 or Locust:

- 20,000 users loading the event page and polling availability;
- a thundering herd of booking attempts at t=0;
- payment confirmation arriving for ~2,000 of them over the following minutes;
- abandoned checkouts expiring and the seats returning to sale.

Pass criteria: no overselling, no negative stock, p95 reservation response
under 1 s, and the database still reconciling exactly — 5,000 tickets sold,
not 5,001.
