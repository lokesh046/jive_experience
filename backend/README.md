# JIVE Events — Backend API

FastAPI modular monolith backing the public website, the customer booking flow,
the admin dashboard, the event-staff QR scanner and (later) the mobile clients.
One versioned REST surface serves all of them.

**Status: catalogue, commerce and fulfilment implemented.** 54 endpoints, a
separately runnable background worker, and four migrations.

**Everyone signs in with Google OAuth 2.0** — customers, event staff and
administrators alike. There are no passwords in this system. Authority comes
from the account row, which an administrator creates with the right role
before that person first signs in; the verified Google email links them.

Not yet live: the **payment provider is unchosen**, so checkout, webhooks and
refunds run against a provider-independent contract whose default adapter
refuses every call. See [Remaining decisions](#remaining-decisions).

---

## Quick start

Requires Docker and [uv](https://docs.astral.sh/uv/).

```bash
cp .env.example .env   # defaults work for local development as-is
make setup             # installs deps, starts PostgreSQL + Redis, creates tables
make dev               # API    → http://localhost:8000
make worker            # worker → in a second terminal
```

Every command: `make`

| Command | Does |
|---|---|
| `make setup` | One-time setup |
| `make dev` | Run the API with reload |
| `make worker` | Run the background worker (outbox + sweeper) |
| `make token EMAIL=you@gmail.com` | Print an access token for Swagger UI |
| `make test` | Run all tests |
| `make check` | Lint + types + tests (what CI runs) |
| `make db` / `make stop` | Start / stop PostgreSQL and Redis |
| `make migrate` | Apply migrations |
| `make migration m="..."` | Create a migration |

Grant the first administrator access (there is no admin yet to grant it):

```bash
.venv/bin/python -m app.cli grant-admin --email you@gmail.com --name "Your Name"
```

No password — they sign in with Google, and that row is what turns the
sign-in into admin access.

Then:

| URL | Purpose |
|---|---|
| `http://localhost:8000/docs` | Swagger UI — try every endpoint (disabled in production) |
| `http://localhost:8000/health` | Liveness probe |
| `http://localhost:8000/api/v1/system/health/ready` | Readiness probe (database + Redis) |

---

## Trying the API in Swagger UI

```bash
make db                                   # PostgreSQL + Redis
make dev                                  # or: make dev PORT=8001 if 8000 is taken
make token EMAIL=you@gmail.com            # prints an access token
```

Open <http://localhost:8000/docs>, press **Authorize**, paste the token, and
every endpoint is callable. The token is remembered across page reloads.

`dev-token` is a CLI command and deliberately **not** an HTTP endpoint: an
endpoint that issues tokens is a backdoor whatever guards it, and one wrong
environment variable would expose it. Running this needs a shell on the
server, which is already full access.

Tokens last 15 minutes. To do it the real way instead — the path the frontend
will use:

1. `GET /api/v1/auth/google/authorize` → returns an `authorization_url`
2. Open it, sign in with Google
3. The redirect to `localhost:3000/auth/google/callback` will not load (no
   frontend yet), but the URL bar contains `?code=...&state=...`
4. Post both to `POST /api/v1/auth/google/callback`

That returns a refresh token good for 30 days, so afterwards use
`POST /api/v1/auth/refresh` rather than repeating the dance.

## Layout

```
backend/
├── app/
│   ├── main.py             create_app() factory, middleware, lifespan
│   ├── cli.py              operator commands (create-admin)
│   ├── dependencies.py     ALL wiring: sessions, settings, services,
│   │                       identity, role guards, rate limits
│   │
│   ├── router/             ONLY routes — no logic, no schemas, no wiring
│   │   └── v1/             system.py · auth.py · users.py · router.py
│   │
│   ├── worker.py           background worker entrypoint (separate process)
│   │
│   ├── services/           business rules; own the transaction boundary
│   │   ├── auth.py         Google sign-in, password login, refresh rotation
│   │   ├── google_oauth.py Google OAuth 2.0 / OIDC client
│   │   ├── user.py         profiles, staff accounts, account status
│   │   ├── audit.py        append-only trail with secret redaction
│   │   ├── catalogue.py    venues, events, ticket categories + cache
│   │   ├── cache.py        Redis response cache, degrades to PostgreSQL
│   │   ├── inventory.py    atomic holds — the concurrency core
│   │   ├── booking.py      booking lifecycle, idempotent creation
│   │   ├── payment.py      one confirmation path for checkout + webhooks
│   │   ├── payment_provider.py  provider-independent contract
│   │   ├── refund.py       policy, state machine, reconciliation
│   │   ├── ticket.py       QR issuance and atomic check-in
│   │   ├── staff.py        event assignments
│   │   └── outbox.py       transactional outbox
│   │
│   ├── repositories/       queries, and nothing else
│   │   ├── base.py         BaseRepository — shared by every repository
│   │   └── user.py · refresh_token.py · audit_log.py
│   │
│   ├── schemas/            Pydantic request/response contracts
│   │   └── auth.py · user.py · system.py
│   │
│   ├── models/             SQLAlchemy tables
│   │   ├── base.py         DeclarativeBase, naming convention, mixins
│   │   └── user.py · refresh_token.py · audit_log.py
│   │
│   ├── core/               cross-cutting, no business logic
│   │   ├── config.py · errors.py · logging.py · middleware.py
│   │   └── money.py · pagination.py · rate_limit.py · redis.py · security.py
│   │
│   └── db/                 session.py · registry.py
├── alembic/                async migration environment
└── tests/
    ├── unit/               no database required
    └── integration/        marked `integration`; needs PostgreSQL
```

### How the layers connect

```
router ──▶ dependencies ──▶ services ──▶ repositories ──▶ models
   │                            │                            ▲
   └──────── schemas            └────────── core ────────────┘
```

The arrows only point one way. `router/` holds route declarations and nothing
else — every dependency it uses comes from `app/dependencies.py`. A service
never imports a router; a repository never holds a rule; a model never imports
a service.


Adding a feature — say events — means one file in each layer, all named for
the feature:

```
app/models/event.py          the table
app/schemas/event.py         the request/response contracts
app/repositories/event.py    the queries  (subclasses BaseRepository)
app/services/event.py        the rules    (owns the transaction)
app/router/v1/events.py      the routes   (thin)
app/dependencies.py          one line: the EventServiceDep alias
```

`BaseRepository` already provides `get`, `get_or_fail`, `find_one`, `exists`,
`count`, `list`, `paginate`, `add`, `delete` and `flush`, so a module's
repository is usually a handful of lines — see
[`app/repositories/user.py`](app/repositories/user.py).

Route handlers contain no business logic. Modules talk to each other through
services, never by importing another module's repository.

---

## Architectural decisions

**Money is integer paise, everywhere.** `BIGINT` in the database, `int` in
Python, minor units on the wire. Floats are never used for money. This is what
both Razorpay and Cashfree expect, so no conversion can drift and refund totals
reconcile exactly against captured totals. Helpers live in `app/core/money.py`.

**PostgreSQL is the source of truth for inventory.** Redis handles caching,
rate limiting and (from Phase 6) the job queue. Ticket availability will be
settled with row-level locks in PostgreSQL. A cache outage must never be able
to oversell an event.

**Services own transactions, not dependencies.** `get_db` yields a session and
never commits on your behalf. For inventory and payments the exact span of a
transaction — and which rows are locked inside it — is part of the correctness
argument, so it is written explicitly in the service.

**UUID primary keys.** Booking, ticket and payment ids appear in URLs, QR
lookups and gateway metadata. Sequential integers would leak sales volume and
invite enumeration.

**All timestamps are `TIMESTAMPTZ`, stored in UTC.** Display conversion happens
at the edge, in the event's own timezone. `app.db.base.utc_now()` is the only
sanctioned clock; `datetime.utcnow()` is banned and the linter enforces it
(ruff `DTZ`).

**One `users` table for all three roles, and one sign-in path.** They are the
same entity with different permissions, and splitting them would duplicate
every "who did this" foreign key.

**Authority lives in the row, not the credential.** A privileged account
exists because an administrator created it with that email and role before the
person ever signed in. Google proves identity; the database decides authority.
No code path can raise a role: an unknown Google account always becomes a
CUSTOMER, whatever the address.

Removing passwords removed credential stuffing, password reset, password
storage and the `/auth/login` endpoint from the system entirely. The trade is
that an admin's Google account security *is* the dashboard's security — see
`docs/google-oauth-setup.md`.

**Google OAuth uses the authorization-code flow with PKCE**, not an ID token
posted from the browser. The `state` is minted server-side and held in Redis,
which is what stops login CSRF; PKCE binds the code to the client; and the
client secret never leaves the server. The same endpoints serve the web app and
future mobile clients.

**Identity is `google_sub`, not the email.** A Google account's email address
can change; its subject identifier cannot. An unverified Google email is
refused outright — accepting one would let an attacker claim an existing
account by address.

**Refresh tokens are stored hashed, and rotate.** Only a SHA-256 digest is
persisted, so a database disclosure yields no usable sessions. Each login
starts a token *family*; presenting an already-rotated token means the chain
has leaked, and the whole family is revoked.

**Access tokens are stateless, the account is not.** The JWT is never read
from the database, which keeps authorisation cheap under load — but the user
row *is* re-read on every request, so a suspension takes effect immediately
rather than whenever the token happens to expire.

**The server refuses to start in production with unsafe settings.** A default
signing key, `CORS_ORIGINS=*`, `DEBUG=true` or missing Firebase credentials
each abort start-up with a message naming every problem at once.

**One error envelope.** Every failure returns
`{"error": {code, message, details, request_id}}`. Clients branch on the stable
`code`, never on the message. Internal exception text is suppressed outside
local and test environments.

**Correlation ids on everything.** `X-Request-ID` is accepted or generated,
bound to the log context, echoed in the response and included in every error
body, so a customer's failed booking can be traced across API, worker and
gateway webhook logs.

---

## Database

Phase 1 schema:

| Table | Purpose |
|---|---|
| `users` | All three roles, separated by CHECK constraints |
| `refresh_tokens` | Hashed rotating sessions with reuse detection |
| `audit_logs` | Append-only trail of sensitive actions |

Deleting a user cascades to their sessions but **not** to the audit trail —
`audit_logs.actor_user_id` is set to NULL so the record of what was done
survives the account that did it. This is tested, not assumed.

### Migrations

```bash
make migration m="add events and ticket categories"   # autogenerate
make migrate                                          # apply
```

Always read the generated migration before committing it. Autogenerate does not
get PostgreSQL ENUM types right on its own: a type shared by two tables is
emitted twice (the second `CREATE TYPE` fails), and `downgrade` leaves the type
behind so the next upgrade fails too. The initial migration shows the pattern —
create the types explicitly at the top of `upgrade()` with `create_type=False`
on the columns, and drop them at the end of `downgrade()`.

`alembic check` fails when the models and migrations have drifted apart; it
runs as part of the integration suite.

---

## Configuration

Every setting is environment-driven; see `.env.example` for the annotated list.

**Managed database.** Set `DATABASE_URL` to the provider's connection string
exactly as the console gives it. Neon, Supabase and RDS all emit libpq URLs,
which asyncpg rejects as-is; `app/core/database_url.py` rewrites the scheme,
translates `sslmode`, drops libpq-only parameters, and disables prepared
statements when the host is a transaction pooler. See `docs/neon-setup.md`,
including the latency constraint — database round-trip time directly caps
ticket throughput.
Nothing secret is committed. `Settings.sqlalchemy_dsn` is excluded from `repr`
so a settings dump cannot leak the database password into the logs.

Before production, these must be set to real values:

- `SECRET_KEY` — `openssl rand -hex 32`
- `POSTGRES_PASSWORD`
- `CORS_ORIGINS` — the real frontend origin, not `*`
- `TRUSTED_HOSTS` — the real hostnames
- `LOG_JSON=true`, `ENVIRONMENT=production`, `DEBUG=false`

---

## Testing

```bash
make test        # everything
```

Unit tests build the app with an overridden `Settings` and never touch
PostgreSQL or Redis. Integration tests are marked `integration` and skip
themselves automatically when PostgreSQL is unreachable, so the suite stays
green on a machine without Docker.

Current coverage (118 tests): configuration, money arithmetic, password
hashing, JWT forgery and expiry, the production start-up guard, audit
redaction, CLI validation, the system endpoints, the error envelope, security
headers, the shared repository, migration up/down/up, model-migration drift,
every user CHECK constraint, every authentication flow, and every role
boundary.

---

## Endpoint map

### Public — no authentication

| Method | Path | Notes |
|---|---|---|
| GET | `/api/v1/events` | Published events. Filters: `city`, `category`, `starts_after`, `starts_before`, `search`, `featured`, `past`. Cached 60 s (`X-Cache` header) |
| GET | `/api/v1/events/cities` | Cities with events, cached 5 min |
| GET | `/api/v1/events/{slug}` | Event detail, cached 120 s |
| GET | `/api/v1/events/{slug}/availability` | Live availability, cached 3 s |
| POST | `/api/v1/payments/webhook` | Signature-verified, deduplicated |

### Customer

| Method | Path | Notes |
|---|---|---|
| POST | `/api/v1/bookings` | Holds inventory. Idempotent on `idempotency_key` |
| GET | `/api/v1/bookings` | Your bookings |
| GET | `/api/v1/bookings/{reference}` | One booking |
| POST | `/api/v1/bookings/{reference}/checkout` | Create/reuse the provider order |
| POST | `/api/v1/bookings/{reference}/verify` | Confirm by asking the provider |
| GET | `/api/v1/bookings/{reference}/refund-quote` | What cancelling would return |
| POST | `/api/v1/bookings/{reference}/cancel` | Cancel + request refund |
| GET | `/api/v1/bookings/{reference}/tickets` | QR tickets |
| GET | `/api/v1/bookings/{reference}/refunds` | Refunds against a booking |
| GET | `/api/v1/tickets` | All of your tickets |

### Event staff scanner

| Method | Path | Notes |
|---|---|---|
| GET | `/api/v1/scanner/events` | Only events you are assigned to |
| POST | `/api/v1/scanner/scan` | Atomic one-time check-in |
| GET | `/api/v1/scanner/events/{event_id}/attendance` | Assignment checked |

### Administrator

| Method | Path |
|---|---|
| GET POST | `/api/v1/admin/venues` |
| PATCH | `/api/v1/admin/venues/{venue_id}` |
| GET POST | `/api/v1/admin/events` |
| GET PATCH | `/api/v1/admin/events/{event_id}` |
| POST | `/api/v1/admin/events/{event_id}/publish` · `/unpublish` · `/cancel` |
| POST | `/api/v1/admin/events/{event_id}/ticket-categories` |
| PATCH DELETE | `/api/v1/admin/ticket-categories/{category_id}` |
| GET | `/api/v1/admin/bookings` · `/{booking_id}` |
| POST | `/api/v1/admin/bookings/{booking_id}/cancel` |
| GET POST | `/api/v1/admin/bookings/{booking_id}/refunds` |
| GET POST | `/api/v1/admin/events/{event_id}/staff` |
| DELETE | `/api/v1/admin/events/{event_id}/staff/{user_id}` |
| GET | `/api/v1/admin/events/{event_id}/attendance` |

Plus the authentication and user endpoints from Phase 2, unchanged.

## Background worker

```bash
make worker                  # or: python -m app.worker
docker compose --profile full up worker
```

Separate process from the API, deliberately: a slow email provider must not
add latency to a checkout, and the two can be scaled and restarted
independently. Two loops run concurrently.

**Outbox loop** claims queued work with `FOR UPDATE SKIP LOCKED`, so several
workers share one queue with no coordination. Failures retry with exponential
backoff capped at an hour; a message that exhausts its attempts becomes
FAILED and stays in the table for an operator.

**Sweeper loop**, every 15 s: releases expired inventory holds, expires
abandoned bookings, recovers outbox messages locked by a worker that died,
and — once a provider is configured — reconciles in-flight payments and
refunds.

Topics: `booking.confirmed` (issues QR tickets), `tickets.issued`,
`refund.process`, `event.cancelled` (batch refunds), `booking.cancelled`,
`refund.completed`.

The worker holds its own database pool (`WORKER_DB_POOL_SIZE`), sized
separately so it cannot starve the API of connections.

## Migrations

```bash
make migrate                                  # apply
make migration m="add artists and portfolio"  # autogenerate, then READ IT
```

| Revision | Adds |
|---|---|
| `274b3ece4c19` | users, refresh_tokens, audit_logs |
| `890335c892c1` | Google OAuth identity (replaces Firebase) |
| `c5b2edd2f5ef` | venues, events, ticket_categories, ticket_reservations, bookings, booking_items, payments, payment_webhook_events, refunds, tickets, ticket_checkins, staff_event_assignments, outbox_messages |
| `601f1aecb6e8` | drops passwords — all roles sign in with Google |

## Remaining decisions

Everything below is a business decision or an account, not engineering work.
Each one has a working contract behind it, so wiring it up is configuration.

| Blocked | Needed | Effect today |
|---|---|---|
| **Payment provider** (Razorpay or Cashfree) | Merchant account + keys | `UnconfiguredPaymentProvider` refuses checkout, webhooks and refunds with `PAYMENT_PROVIDER_NOT_CONFIGURED`. Implement one adapter in `app/services/payment_provider.py`; nothing else changes |
| **Cancellation policy** numbers | Tier table per event | `refund-quote` returns `eligible: false` with a reason. Shape is settled: `{"tiers": [{"hours_before": 168, "percent": 100}]}` |
| **Transactional email/SMS** | SMTP or provider credentials | Tickets are issued and stored; delivery is logged, not sent |
| **Phone verification** | SMS provider | Booking requires a phone number but cannot yet verify it, so the per-account purchase limit is weaker than intended — see `docs/anti-bot.md` |
| **Object storage / CDN** | Bucket + credentials | Image URLs are stored as given; nothing is uploaded by the API |

Also not implemented, deliberately: `EventStatus.SOLD_OUT` is never set
automatically — `is_sold_out` is computed from live inventory instead, so
there is no second source of truth to drift.

## Roadmap

| Phase | Scope | Depends on |
|---|---|---|
| **1 ✅** | Foundation, config, DB layer, migrations, logging, tests | — |
| **2 ✅** | Auth: Google OAuth 2.0 (PKCE), JWT issue/rotate with reuse detection, RBAC, admin + staff login, user management, audit trail | — |
| **3 ✅** | Catalogue: venues, events, ticket categories, public listing with Redis caching, admin CRUD | — |
| **4 ✅** | Commerce: atomic inventory holds, idempotent bookings, provider-independent payments, refund state machine | gateway account to go live |
| **5 ✅** | Fulfilment: QR issuance, staff scanner with atomic check-in, staff assignments, outbox worker | — |
| 6 | Content: services, artists, portfolio, enquiries, notifications, reports, CSV export | email provider |
| 7 | Deployment: reverse proxy, TLS, backups, monitoring, load test, runbook | 6 |

---

## Known gaps after Phase 1

- **Phone numbers are not yet verified.** The endpoint stores one; Phase 4
  must require a *verified* number before a reservation, or the per-account
  purchase limit is unenforceable. See `docs/anti-bot.md`.
- **No CI workflow yet.** It belongs at the repository root
  (`.github/workflows/`), which is outside this folder. `make check` is the
  command it should run.
- **Staff event assignment** is not built yet — it needs the events table, so
  it lands in Phase 3.
- **Tokens are returned in the response body**, not set as HttpOnly cookies.
  This works for the web app and for future mobile clients from one code path;
  revisit if the frontend wants cookie sessions.
- **`alembic check` needs a live database**, so model/migration drift is caught
  by the integration suite rather than by the unit suite.
- **Blocked on decisions** — see `docs/open-decisions.md`.
- **Setup guides** — `docs/google-oauth-setup.md`, `docs/neon-setup.md`.
- **Capacity target** — 5,000 seats selling out in ~2 minutes; the design this
  requires is in `docs/capacity.md`, and a load test is a Phase 4 deliverable.
- **Bot and scalper controls** — `docs/anti-bot.md`. OTP login must gate
  reservation, not checkout, or the per-account limit cannot be enforced.
