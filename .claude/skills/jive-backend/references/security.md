# Security

## Roles

Three: `ADMIN`, `CUSTOMER`, `EVENT_STAFF`. Enforced in the backend on every
endpoint. The UI hiding a button is not access control.

- **Everyone** signs in with Google OAuth 2.0 — customers, event staff and
  administrators. There are no passwords in this system.
- Authorization-code flow with PKCE. The `state` and PKCE verifier live in
  Redis, the client secret never leaves the server, and an unverified Google
  email is refused.
- Identity is `google_sub`, never the email: a Google email can change.
- **Authority is on the row, not the credential.** A privileged account exists
  because an administrator pre-created it with that email and role. Signing in
  can only ever produce a CUSTOMER — never add a code path that reads a role
  from anything the caller supplies.
- Staff may only act on events they are assigned to — check the assignment,
  not just the role.

## Implemented in Phase 2

`app/core/security.py`, `app/services/auth.py`, `app/services/google_oauth.py`
and `app/dependencies.py` already provide: Argon2id hashing, access-token issue and
verification, refresh rotation with family-based reuse detection, the full
Google OAuth flow, the RBAC dependencies, the account-state checks and the
production start-up guard. Reuse them — do not write a second way to
authenticate.

## Tokens

- Access tokens are short-lived (15 min) and are not stored.
- Refresh tokens are stored as a SHA-256 hash, rotate on every use, and belong
  to a family. Presenting an already-rotated token means it leaked: revoke the
  whole family.
- Revoke on logout, password change, suspension.

## Rate limiting

`app/core/rate_limit.py`. Fail-open for public browsing (a cache outage must
not take the site down); **fail-closed for authentication** (losing the limiter
must not open a credential-stuffing window). Already applied to the OAuth
endpoints, password login and refresh.

## Webhooks

Verify the signature before parsing the body. Deduplicate by gateway event id
with a UNIQUE constraint. Respond quickly and do the work idempotently.

## Secrets

- Environment only. Never in code, tests, fixtures or the repository.
- Firebase service-account credentials, gateway secrets and database
  credentials stay server-side and are never exposed to the frontend.
- `Settings.sqlalchemy_dsn` is excluded from `repr` so a settings dump cannot
  leak the database password into the logs. Keep it that way when adding
  secret fields — use `SecretStr`.

## Input and uploads

- Validate everything with Pydantic at the edge.
- File uploads: check content type and real file signature, cap the size,
  generate the stored filename yourself, and never serve uploads from a path
  the user controls.
- Queries go through SQLAlchemy. If raw SQL is genuinely needed, it is
  parameterised — never f-strings.

## Audit

Write an `audit_logs` row for: event publish and cancel, price and inventory
changes, booking and refund decisions, staff assignment, privileged login, and
every manual override of an automated money flow. Snapshots must be redacted —
no secrets, no card data, no raw tokens.

## Logging

Structured JSON with a correlation id. Never log OTPs, tokens, passwords,
full gateway payloads or anything that would let someone replay a request.
