# Using Neon as the database

Neon is serverless PostgreSQL. The backend supports it with no code changes —
paste the connection string into `DATABASE_URL` and the app normalises it for
asyncpg automatically.

## Setup

1. <https://console.neon.tech> → **New Project**.
2. **Choose the region closest to where the API will run.** See the latency
   warning below; this is the one decision here that is expensive to change.
3. Postgres version: 16 or later.
4. **Connection Details** → copy the connection string. It looks like:

   ```
   postgresql://neondb_owner:npg_xxxx@ep-cool-name-a1b2c3d4-pooler.ap-southeast-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require
   ```

5. In `backend/.env`:

   ```bash
   DATABASE_URL=postgresql://neondb_owner:npg_xxxx@ep-....neon.tech/neondb?sslmode=require
   ```

   `DATABASE_URL` overrides the discrete `POSTGRES_*` settings, which can stay
   as they are for local work.

6. Apply the schema:

   ```bash
   make migrate
   ```

7. Create the first administrator:

   ```bash
   .venv/bin/python -m app.cli create-admin --email ops@example.com --name "Ops"
   ```

## What the app does with that URL

A Neon URL is a **libpq** URL. asyncpg is not libpq and rejects several of its
parameters — pasted unchanged it fails with
`connect() got an unexpected keyword argument 'sslmode'`.
`app/core/database_url.py` handles this:

| In the URL | What the app does |
|---|---|
| `postgresql://` | Rewritten to `postgresql+asyncpg://` |
| `sslmode=require` | Removed from the URL, re-applied as `ssl="require"` |
| `channel_binding=require` | Removed (libpq-only) |
| host contains `-pooler.` | Prepared-statement caches disabled, local pool reduced to 5 |

### Why the pooled endpoint needs prepared statements off

Neon's `-pooler` endpoint is PgBouncer in **transaction** mode: consecutive
statements can land on different backends. A server-side prepared statement
created on one is absent on the next, and the symptom is
`prepared statement "__asyncpg_stmt_1__" does not exist` — which appears only
after a reconnect, under concurrency. That is to say: not in development, and
during a ticket release.

### Pooled or direct?

- **Pooled** (`-pooler`) — use this for the API. Many short connections.
- **Direct** — use for migrations and one-off admin work if you prefer; both
  work. Neon's own guidance is to use pooled for applications.

## Latency: the thing that decides whether this works

Every query is a network round trip. The booking path takes a row lock and
holds it for the length of that trip, so **database latency directly caps how
many tickets per second can be sold**.

| Round trip | Realistic reservations/sec | Against the 42/sec target |
|---|---|---|
| ~1 ms (same region) | several hundred | comfortable |
| ~20 ms (nearby region) | ~50 | marginal |
| ~200 ms (cross-continent) | ~5 | **fails** |

### Measured on this project — 2026-11-20

The configured Neon project is in **`us-east-2` (Ohio)**. Measured from a
development machine in India:

| | |
|---|---|
| First connect | **5,845 ms** (TLS + cold start) |
| Warm round trip | **median 528 ms**, p95 625 ms |
| Implied reservation ceiling | **~1 per second** |
| Required for the agreed target | ~17–40 per second |

That is roughly 40× short of what a 5,000-seat two-minute sale needs.

Two things that measurement does and does not say:

* It **does** say local development against this database will be painful —
  every query costs half a second.
* It does **not** by itself condemn production. What matters in production is
  the round trip from the **API server** to Neon, not from a laptop. If the
  VPS is also in `us-east-2`, latency is ~1 ms and everything is fine.

So the decision is not "Neon or not", it is **where the API server runs
relative to the database**:

| API server | Neon region | Verdict |
|---|---|---|
| Ohio (`us-east-2`) | Ohio | Fine — co-located |
| India / Singapore | Ohio | **Will not work** for a timed sale |
| India / Singapore | Nearest Asian region | Measure it; likely acceptable |

If customers are in India, serving the website from Ohio also adds latency to
every page load. The usual answer is: API server and database in the same
region, close to the customers, with a CDN in front of the public pages.

**Put Neon in the same region as the API server.** If the VPS is in India,
pick the nearest Neon region and measure before committing. If the only
acceptable Neon region is far away, run PostgreSQL next to the app instead —
this is a case where the managed service is the wrong trade.

Measure it, do not assume:

```sql
-- from the application server
\timing on
SELECT 1;
```

## Autosuspend and cold starts

Neon suspends compute after an idle period and the next connection pays a cold
start. For a ticket release that is unacceptable — the first buyers would see
the slowest responses.

Before any announced sale:

- Disable autosuspend, or set the idle window long enough to cover the sale.
- Warm the database a few minutes before, and keep the API running so the pool
  holds open connections.

## Connection limits

Neon caps connections by plan, and a serverless database charges for compute
time. The app already keeps its pool small behind a pooler (5 + 5). If you run
several API containers, multiply that by the container count and check it
against the plan limit before a release.

## Backups

Neon provides point-in-time restore on paid plans; the free tier's retention is
short. The deployment phase still needs **off-server logical backups**
(`pg_dump` on a schedule, stored elsewhere) — a provider-side restore does not
protect against a mistaken migration or a deleted project.

## Checklist before a real ticket sale

- [ ] Neon region is the same as — or adjacent to — the API server
- [ ] Measured round-trip latency from the API server, written down
- [ ] Autosuspend disabled or window covers the sale
- [ ] Plan's connection limit ≥ pool size × container count
- [ ] Off-server backups running and a restore tested
- [ ] Load test run against this database, not against localhost
