# Database

PostgreSQL is the source of truth. SQLAlchemy 2.x async, Alembic migrations.

## Conventions

- **UUID primary keys** (`UUIDPrimaryKeyMixin`). Ids appear in URLs, QR
  lookups and gateway metadata; sequential integers would leak sales volume
  and invite enumeration.
- **`TIMESTAMPTZ`, stored UTC** (`TimestampMixin`). Convert for display in the
  event's timezone at the edge. Use `app.db.base.utc_now()`;
  `datetime.utcnow()` is banned and ruff's `DTZ` rules enforce it.
- **Money is `BIGINT` paise.** Never `FLOAT`, never `DOUBLE PRECISION`.
- **Constraint names are deterministic** via the metadata naming convention —
  do not hand-name constraints, and do not rely on anonymous ones.
- **Enums**: `StrEnum` in Python, native PostgreSQL enum type.

## Put rules in the database when they protect money or access

Application code can be wrong. The `users` table is the model to copy: CHECK
constraints make it impossible to store a CUSTOMER row with a password hash, so
the OTP path cannot mint a privileged account even if the service layer has a
bug.

Candidates for a database constraint:

- Inventory can never go negative.
- A ticket can be checked in once.
- A gateway payment id and a webhook event id appear at most once (UNIQUE).
- Refunded total can never exceed the captured total.

## Migrations

```bash
make migration m="add events and ticket categories"
make migrate
```

**Always read the generated migration.** Autogenerate gets two things wrong:

1. **ENUM types shared by two tables** are emitted twice; the second
   `CREATE TYPE` fails. Create them once at the top of `upgrade()` and set
   `create_type=False` on the columns.
2. **`downgrade()` leaves the types behind**, so the next upgrade fails.
   Drop them at the end of `downgrade()`.
3. **CHECK constraint changes are not detected at all.** `alembic check` stays
   silent, so the constraint tests in the integration suite are what catch a
   forgotten one. Write those statements by hand.
4. **Wrap every constraint name in `op.f(...)`.** Without it the metadata
   naming convention is applied a second time and you get
   `ck_users_ck_users_customer_has_no_password`, which then fails to drop.

The initial migration
(`backend/alembic/versions/20261120_0748_initial_identity_audit.py`) shows the
pattern. Copy it.

Other rules:

- Every migration must downgrade cleanly. `downgrade → upgrade` is the path a
  failed production deploy takes; the integration suite tests it.
- Adding a NOT NULL column to a populated table: add it nullable, backfill,
  then set NOT NULL — three steps, not one.
- Index creation on a large live table should be `CONCURRENTLY` (which needs
  `transaction_per_migration` and an autocommit block).
- `alembic check` fails when models and migrations drift; it runs in the
  integration suite.

## Indexes

Add one when a query filters or sorts on the column in a request path. Current
known hot paths: events by status + date, bookings by customer, bookings by
event, tickets by QR token hash, payments by gateway id, check-ins by event.

Composite index column order follows the query: equality columns first, then
the range or sort column.

## Deletion

Prefer status columns over deleting rows for anything a customer has paid for.
Bookings, payments, refunds and tickets are financial records — cancel them,
never delete them. Audit rows survive the account that created them
(`ON DELETE SET NULL`), while sessions do not (`ON DELETE CASCADE`).
