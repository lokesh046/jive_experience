"""Database URL normalisation.

Managed PostgreSQL providers (Neon, Supabase, RDS) hand out **libpq** URLs.
asyncpg is not libpq and rejects several of its parameters outright, so a URL
pasted straight from the Neon console fails at the first connection with
`connect() got an unexpected keyword argument 'sslmode'`.

This module converts such a URL into one SQLAlchemy's asyncpg dialect accepts,
and works out the connection arguments the provider needs.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

ASYNC_SCHEME = "postgresql+asyncpg"

# Recognised by libpq/psycopg, not by asyncpg. Dropped from the URL; `sslmode`
# is translated into a connection argument rather than discarded.
LIBPQ_ONLY_PARAMS = frozenset(
    {
        "sslmode",
        "channel_binding",
        "sslrootcert",
        "sslcert",
        "sslkey",
        "gssencmode",
        "target_session_attrs",
        "application_name",
        "connect_timeout",
        "options",
    }
)

# sslmode values that mean "encrypt the connection".
SSL_REQUIRED_MODES = frozenset({"require", "verify-ca", "verify-full", "prefer", "allow"})


def normalize_database_url(url: str) -> str:
    """Return a DSN SQLAlchemy's asyncpg dialect can use.

    * `postgres://` and `postgresql://` become `postgresql+asyncpg://`
    * libpq-only query parameters are removed

    An existing `postgresql+asyncpg://` URL is left alone apart from the
    parameter cleanup, so a hand-written DSN keeps working.
    """
    parts = urlsplit(url.strip())

    scheme = parts.scheme
    if scheme in {"postgres", "postgresql"}:
        scheme = ASYNC_SCHEME

    kept = [(key, value) for key, value in parse_qsl(parts.query) if key not in LIBPQ_ONLY_PARAMS]

    return urlunsplit((scheme, parts.netloc, parts.path, urlencode(kept), parts.fragment))


def requires_ssl(url: str) -> bool:
    """Whether the original URL asked for an encrypted connection.

    Managed providers are reachable only over TLS, and every one of them says
    so with `sslmode` — which is exactly the parameter asyncpg cannot read.
    """
    query = dict(parse_qsl(urlsplit(url).query))
    return query.get("sslmode", "").lower() in SSL_REQUIRED_MODES


def is_transaction_pooler(url: str) -> bool:
    """Whether the host is a connection pooler.

    Neon's pooled endpoint is `...-pooler.<region>.aws.neon.tech`; Supabase
    uses `pooler.supabase.com`. Both run PgBouncer in transaction mode, where
    server-side prepared statements break: a statement prepared on one backend
    will not be there on the next request.
    """
    host = (urlsplit(url).hostname or "").lower()
    return "-pooler." in host or "pooler." in host or ":6543" in url


def asyncpg_connect_args(url: str, *, application_name: str) -> dict[str, Any]:
    """Connection arguments for this URL."""
    args: dict[str, Any] = {"server_settings": {"application_name": application_name}}

    if requires_ssl(url):
        args["ssl"] = "require"

    if is_transaction_pooler(url):
        # Prepared statements cannot survive a transaction pooler. Without
        # this the app works until a reconnect, then fails with
        # "prepared statement ... does not exist" under concurrency — which is
        # exactly when a ticket release is happening.
        args["statement_cache_size"] = 0
        args["prepared_statement_cache_size"] = 0

    return args
