---
name: jive-backend
description: Backend conventions for the JIVE event management platform (FastAPI + PostgreSQL + Redis in backend/). Use for any backend task — adding a module, endpoint, model, migration or test; anything touching money, ticket inventory, bookings, payments, refunds, QR tickets or check-in. Enforces the module layout, transaction policy and money rules so new code matches what is already there.
references:
  - adding-a-module
  - database
  - money-and-concurrency
  - testing
  - security
---

# JIVE Backend Skill

Conventions for `backend/` — a FastAPI modular monolith serving the public
website, customer bookings, the admin dashboard, the staff QR scanner and
future mobile clients from one versioned REST surface.

**Read the existing code before adding to it.** This skill records decisions
already made and tested. When this file and the code disagree, the code wins —
update this file in the same change.

## Non-negotiables

These five rules protect money, inventory and access control. Breaking any of
them is a bug even if the tests pass.

1. **Money is integer paise.** `BIGINT` in PostgreSQL, `int` in Python, minor
   units on the wire. Never `float`. Use `app/core/money.py`.
2. **Prices are computed on the server.** A client-submitted total is input to
   validate, never a figure to charge.
3. **PostgreSQL is the source of truth for inventory.** Redis is cache, rate
   limiting and the job queue. A Redis outage must not be able to oversell.
4. **Permissions are enforced in the backend**, on every endpoint, for every
   role — never only in the UI.
5. **Never trust a frontend payment result.** Confirm server-side against the
   gateway, and verify every webhook signature.

## Layered structure

The backend is organised by **layer**, not by feature. One concern per folder:

```
app/router/        ONLY route declarations. No logic, no schemas, no wiring.
app/dependencies.py  ALL wiring: sessions, settings, services, auth, limits
app/schemas/       Pydantic request/response contracts
app/services/      business rules. Owns the transaction boundary.
app/repositories/  queries, and nothing else
app/models/        SQLAlchemy tables
app/core/          cross-cutting: config, errors, security, money, limits
app/db/            engine, session, model registry
```

Dependencies point one way only:

```
router ──▶ dependencies ──▶ services ──▶ repositories ──▶ models
   │                            │                            ▲
   └──────── schemas            └────────── core ────────────┘
```

A route file contains route declarations and nothing else — no helper
functions, no response classes, no limiter definitions. Everything it depends
on is imported from `app/dependencies.py`. A repository never holds a rule. A
model never imports a service. A service may call another service; it must not
reach into another feature's repository.

## Where does this code go?

```
New backend work
├─ HTTP endpoint ──────────── app/router/v1/<feature>s.py
├─ Business rule / workflow ─ app/services/<feature>.py
├─ Database query ─────────── app/repositories/<feature>.py
├─ Table ──────────────────── app/models/<feature>.py  + a migration
├─ Request/response shape ─── app/schemas/<feature>.py
├─ Dependency / wiring ────── app/dependencies.py
├─ Used everywhere ────────── app/core/   (never business logic)
└─ Whole new feature ──────── see references/adding-a-module.md
```

One feature = one file per layer, each named for the feature.

## Which feature file?

```
auth          token issue/rotate/revoke, Google OAuth sign-in, password login
users         profiles, roles, account state
staff         staff accounts, event assignments
events        events, venues, ticket categories, publish/cancel
inventory     capacity, reservations, expiry  ← concurrency lives here
bookings      booking lifecycle and price calculation
payments      gateway orders, verification, webhooks, reconciliation
refunds       eligibility, refund records, gateway refunds, reconciliation
tickets       per-attendee ticket + QR token issue
checkin       scanner validation and atomic one-time check-in
services      company service pages
artists       artist profiles
portfolio     past events, gallery
enquiries     enquiry capture and admin pipeline
notifications outbox-driven email/SMS
reports       sales, attendance, CSV export
audit         append-only trail of sensitive actions
```

Unsure between two? Put it where the data lives.

## Commands

```bash
make setup                      # first time: deps + database + tables
make dev                        # run the API
make test                       # all tests
make check                      # lint + types + tests — run before finishing
make migration m="add events"   # create a migration
make migrate                    # apply migrations
```

## Before finishing any backend change

1. `make check` passes — lint, `mypy --strict`, and the full test suite.
2. New behaviour has a test. Database constraints are tested against real
   PostgreSQL, not mocked.
3. Schema change ⇒ a migration, reviewed by hand (autogenerate gets
   PostgreSQL ENUMs wrong — see `references/database.md`).
4. No secret, credential or gateway key added to code, tests or fixtures.
5. Sensitive admin action ⇒ an `audit_logs` row.

## Reference files

| File | Read it when |
|---|---|
| `references/adding-a-module.md` | Creating a module or endpoint |
| `references/database.md` | Models, migrations, constraints, indexes |
| `references/money-and-concurrency.md` | Money, inventory, bookings, payments, refunds |
| `references/testing.md` | Writing tests |
| `references/security.md` | Auth, roles, rate limits, webhooks, uploads |

## Protecting an endpoint

Authorisation is a dependency, never an `if` inside the handler:

```python
from app.modules.auth.dependencies import (
    CurrentUser, RequireAdmin, RequireStaff, RequireAdminOrStaff,
)

@router.post("/events")
async def create_event(actor: RequireAdmin, session: DbSession): ...
```

- `CurrentUser` — any signed-in account.
- `RequireAdmin` / `RequireStaff` / `RequireCustomer` / `RequireAdminOrStaff`.
- Role alone is not enough for staff: from Phase 3, also check that the staff
  member is assigned to the event they are acting on.
- The user row is re-read on every request, so a suspension takes effect at
  once rather than when the access token expires.

## Project state

Phases 1 (foundation) and 2 (auth, users, audit) are complete and tested.
Phase 3 (events and catalogue) is next.

Capacity and policy constraints already agreed — read before Phase 4:

| Document | Holds |
|---|---|
| `backend/docs/capacity.md` | 5,000 seats selling out in ~2 minutes, and what that requires |
| `backend/docs/anti-bot.md` | Scalper controls; OTP must gate reservation, not checkout |
| `backend/docs/open-decisions.md` | Payment gateway and refund policy, both still unanswered |
