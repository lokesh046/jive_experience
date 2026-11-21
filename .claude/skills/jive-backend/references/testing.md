# Testing

```bash
make test     # everything
make check    # lint + types + tests
```

## Layout

```
tests/
├── unit/          no database — settings, pure logic, endpoints via ASGI
└── integration/   marked `integration` — real PostgreSQL
```

Integration tests skip themselves when PostgreSQL is unreachable, so the suite
stays green without Docker.

## Fixtures

| Fixture | Gives you |
|---|---|
| `client` | `AsyncClient` against the app, no database |
| `db_connection` | Connection; rolled back after the test |
| `db_session` | ORM session; `commit()` is savepoint-scoped and rolled back |

## Rules

- **Test behaviour, not implementation.** Assert what a caller observes.
- **Database constraints are tested against real PostgreSQL**, never mocked —
  the point is that the database rejects the row.
- A rejected INSERT aborts the whole transaction. To test several rejections
  in one test, wrap each in `conn.begin_nested()` (a SAVEPOINT).
- **Mock the payment gateway** in automated tests; use the provider sandbox
  for manual integration testing. Never put real credentials in a test.
- Name tests as a sentence about the behaviour:
  `test_customer_cannot_hold_a_password`, not `test_user_2`.

## What must have a test

Money, inventory and access control are not covered by "it looked right":

- Simultaneous bookings for the last ticket.
- Reservation expiry, and payment arriving after it.
- Duplicate webhooks (same gateway event id twice).
- Duplicate refund requests.
- Simultaneous scans of the same QR ticket.
- A staff member scanning an event they are not assigned to.
- Every role boundary: can a customer reach an admin endpoint?

Concurrency claims need a concurrent test — two real sessions racing, not one
session called twice.
