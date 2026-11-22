"""Application configuration.

All configuration is environment-driven. Nothing secret is ever hard-coded or
committed; see `.env.example` for the full list of variables.
"""

from __future__ import annotations

import json
from enum import StrEnum
from functools import lru_cache
from typing import Annotated, Any, Literal

from pydantic import Field, SecretStr, computed_field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from app.core.database_url import (
    asyncpg_connect_args,
    is_transaction_pooler,
    normalize_database_url,
)


class Environment(StrEnum):
    LOCAL = "local"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ------------------------------------------------------------- app ----
    app_name: str = "JIVE Events API"
    environment: Environment = Environment.LOCAL
    debug: bool = False
    api_v1_prefix: str = "/api/v1"

    # Host timezone used to render UTC timestamps when an event carries no
    # timezone of its own. Storage is always UTC.
    default_timezone: str = "Asia/Kolkata"
    default_currency: Literal["INR"] = "INR"

    # --------------------------------------------------------- security ----
    # Signing key for backend-issued access/refresh tokens. Must be overridden
    # outside local development.
    secret_key: SecretStr = SecretStr("dev-only-insecure-change-me")
    access_token_ttl_seconds: Annotated[int, Field(ge=60, le=3600)] = 900  # 15 min
    refresh_token_ttl_seconds: Annotated[int, Field(ge=3600)] = 60 * 60 * 24 * 30  # 30 d

    # NoDecode: this class owns the parsing so that both `A,B` and a JSON
    # list work identically whether the value comes from the environment,
    # a .env file or a direct constructor call.
    # Signs QR tokens. Separate from `secret_key` on purpose: session keys
    # should be rotatable at will, and rotating this one invalidates every
    # ticket that has not yet been scanned.
    qr_signing_key: SecretStr | None = None

    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:3000"]
    trusted_hosts: Annotated[list[str], NoDecode] = ["*"]

    # ----------------------------------------------------- google oauth ----
    # Customer sign-in. The client secret never leaves the server.
    google_client_id: str | None = None
    google_client_secret: SecretStr | None = None

    # Where Google sends the user back. Must match a redirect URI registered
    # in the Google Cloud console exactly, including scheme and trailing path.
    google_redirect_uri: str = "http://localhost:3000/auth/google/callback"

    # How long a pending sign-in may stay open. Short: the state and PKCE
    # verifier are single-use and the user is mid-flow.
    oauth_state_ttl_seconds: int = 600

    # Phone numbers outside these country codes are refused. The phone is
    # collected after sign-in and verified before a reservation.
    allowed_phone_country_codes: Annotated[list[str], NoDecode] = ["+91"]

    # ----------------------------------------------------- auth limits ----
    # Fail-closed: if Redis is unavailable these endpoints reject rather than
    # leave an unmetered window for automated account creation.
    oauth_rate_limit_times: int = 20
    oauth_rate_limit_seconds: int = 300

    # -------------------------------------------------------- commerce ----
    # How long inventory is held while the customer pays. Shorter than the
    # ten minutes in the original brief: at a two-minute sellout, seats held
    # by people who never pay are the scarcest thing in the system.
    # See docs/capacity.md.
    reservation_hold_seconds: Annotated[int, Field(ge=60, le=1800)] = 300

    # Payments still in flight after this long are reconciled against the
    # provider rather than waiting for a webhook that may never arrive.
    payment_reconcile_after_seconds: int = 600

    # Chosen later: "razorpay" or "cashfree". Until then the provider
    # adapter refuses every call rather than pretending to succeed.
    payment_provider: str | None = None
    payment_key_id: str | None = None
    payment_key_secret: SecretStr | None = None
    payment_webhook_secret: SecretStr | None = None

    # Cloudinary hosts event photos. The browser uploads straight to it with a
    # short-lived signature from this API, so the secret never leaves the server.
    cloudinary_cloud_name: str | None = None
    cloudinary_api_key: str | None = None
    cloudinary_api_secret: SecretStr | None = None

    # Transactional email over SMTP (Gmail: smtp.gmail.com, port 587, an app
    # password). Unset means email is switched off: the worker logs and moves on
    # instead of retrying a message that can never be sent.
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    mail_from: str | None = None
    mail_from_name: str = "JIVE Events"
    # Where customers open their booking from an email.
    public_site_url: str = "http://localhost:3000"

    # Reminder email to ticket holders this many hours before the event starts.
    reminder_hours_before: Annotated[int, Field(ge=1, le=168)] = 24
    reminder_sweep_interval_seconds: float = 900.0

    # --------------------------------------------------------- worker ----
    worker_poll_interval_seconds: float = 2.0
    worker_batch_size: int = 20
    worker_sweep_interval_seconds: float = 15.0
    # The API and the worker hold separate pools against the same database;
    # size them independently so a busy worker cannot starve the API.
    worker_db_pool_size: int = 5
    worker_db_max_overflow: int = 5

    # --------------------------------------------------------- database ----
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "jive"
    postgres_password: SecretStr = SecretStr("jive")
    postgres_db: str = "jive_events"

    db_pool_size: int = 10
    db_max_overflow: int = 10
    db_pool_timeout: int = 30
    db_pool_recycle: int = 1800
    db_echo: bool = False

    # Full DSN override, taking precedence over the discrete fields above.
    # Paste a managed-provider URL here verbatim — Neon, Supabase and RDS all
    # hand out libpq URLs, which are normalised for asyncpg automatically.
    database_url: str | None = None

    # ------------------------------------------------------------ redis ----
    redis_url: str = "redis://localhost:6379/0"

    # ---------------------------------------------------- observability ----
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_json: bool = True

    # ------------------------------------------------------ rate limits ----
    rate_limit_enabled: bool = True
    # Generic per-IP ceiling for unauthenticated public endpoints.
    rate_limit_default_times: int = 120
    rate_limit_default_seconds: int = 60

    @field_validator("cors_origins", "trusted_hosts", "allowed_phone_country_codes", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        """Accept `A,B,C` or a JSON list."""
        if not isinstance(value, str):
            return value
        text = value.strip()
        if text.startswith("["):
            return json.loads(text)
        return [item.strip() for item in text.split(",") if item.strip()]

    @computed_field(repr=False)  # type: ignore[prop-decorator]
    @property
    def sqlalchemy_dsn(self) -> str:
        """Async DSN used by the application and by Alembic."""
        if self.database_url:
            return normalize_database_url(self.database_url)
        return (
            f"postgresql+asyncpg://{self.postgres_user}:"
            f"{self.postgres_password.get_secret_value()}@"
            f"{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def database_connect_args(self) -> dict[str, Any]:
        """Driver arguments: TLS, and pooler-safe settings when required."""
        return asyncpg_connect_args(
            self.database_url or self.sqlalchemy_dsn, application_name=self.app_name
        )

    @property
    def uses_transaction_pooler(self) -> bool:
        """Whether the database is reached through a transaction pooler.

        The app keeps its own small pool in that case: a serverless provider
        charges for connections and a pooler already multiplexes them, so a
        large local pool buys nothing and can exhaust the provider's limit.
        """
        return is_transaction_pooler(self.database_url or "")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_production(self) -> bool:
        return self.environment is Environment.PRODUCTION

    @property
    def qr_secret(self) -> str:
        """Key used to derive ticket QR tokens.

        Falls back to `secret_key` so nothing breaks before it is configured,
        but production should set it explicitly — see `assert_production_ready`.
        """
        if self.qr_signing_key:
            return self.qr_signing_key.get_secret_value()
        return self.secret_key.get_secret_value()

    @property
    def email_configured(self) -> bool:
        return bool(self.smtp_host and self.smtp_username and self.smtp_password and self.mail_from)

    @computed_field(repr=False)  # type: ignore[prop-decorator]
    @property
    def google_oauth_configured(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret)


DEFAULT_SECRET_KEY = "dev-only-insecure-change-me"
MIN_SECRET_KEY_LENGTH = 32


def assert_production_ready(settings: Settings) -> None:
    """Refuse to start a production server with development defaults.

    Each of these has been a real production incident somewhere: a default
    signing key means anyone can mint an admin token; `CORS_ORIGINS=*` with
    credentials allows any site to call the API as a signed-in user. Failing
    loudly at boot is far better than discovering it from traffic.
    """
    if not settings.is_production:
        return

    problems: list[str] = []
    secret = settings.secret_key.get_secret_value()
    if secret == DEFAULT_SECRET_KEY:
        problems.append("SECRET_KEY is still the development default")
    elif len(secret) < MIN_SECRET_KEY_LENGTH:
        # RFC 7518 §3.2: an HMAC-SHA256 key shorter than the hash output
        # weakens the signature. `openssl rand -hex 32` gives 64 characters.
        problems.append(
            f"SECRET_KEY must be at least {MIN_SECRET_KEY_LENGTH} characters "
            "(use: openssl rand -hex 32)"
        )
    if settings.debug:
        problems.append("DEBUG must be false in production")
    if "*" in settings.cors_origins:
        problems.append("CORS_ORIGINS must name real origins, not '*'")
    if settings.trusted_hosts == ["*"]:
        problems.append("TRUSTED_HOSTS must name real hostnames")
    if not settings.google_oauth_configured:
        problems.append("Google OAuth is not configured; customer sign-in would fail")
    if settings.google_redirect_uri.startswith("http://"):
        problems.append("GOOGLE_REDIRECT_URI must use https in production")
    if not settings.log_json:
        problems.append("LOG_JSON should be true so logs are parseable")
    if not settings.qr_signing_key:
        # Sharing the session key means any rotation of SECRET_KEY voids every
        # ticket that has not yet been scanned — discovered at a gate.
        problems.append(
            "QR_SIGNING_KEY must be set separately from SECRET_KEY (use: openssl rand -hex 32)"
        )

    if problems:
        raise RuntimeError("Refusing to start in production:\n  - " + "\n  - ".join(problems))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings accessor — the single entry point for configuration."""
    return Settings()
