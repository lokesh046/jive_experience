"""Operational commands.

    python -m app.cli grant-admin --email ops@gmail.com --name "Ops"
    python -m app.cli dev-token   --email ops@gmail.com

Used to grant the **first** administrator access, since the API requires an
existing admin to grant another. After that, administrators add each other
through the dashboard.

There is no password: every account signs in with Google OAuth 2.0. This
command creates the row that turns a Google sign-in into admin access, so the
email must be exactly the address on that person's Google account.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from pydantic import TypeAdapter, ValidationError
from pydantic.networks import EmailStr

from app.core.config import Environment, get_settings
from app.core.security import create_access_token
from app.db.session import create_engine, dispose_engine, get_sessionmaker
from app.models.user import User, UserRole, UserStatus
from app.repositories.user import UserRepository

_EMAIL = TypeAdapter(EmailStr)


def validate_email(email: str) -> str | None:
    """Validate exactly as the API does.

    Without this the CLI will happily create an account whose email the
    sign-in path then refuses — for example a reserved TLD such as `.test` —
    and the administrator can never sign in.
    """
    try:
        return str(_EMAIL.validate_python(email)).lower()
    except ValidationError:
        return None


async def grant_access(email: str, full_name: str, role: UserRole) -> int:
    validated = validate_email(email)
    if validated is None:
        print(f"'{email}' is not a valid email address.", file=sys.stderr)
        return 1

    create_engine(get_settings())
    try:
        async with get_sessionmaker()() as session:
            users = UserRepository(session)
            existing = await users.by_email(validated)

            if existing is not None:
                if existing.is_privileged:
                    print(
                        f"{validated} already has {existing.role.value} access.",
                        file=sys.stderr,
                    )
                    return 1
                # They already booked tickets as a customer; promote that row
                # rather than creating a second one for the same person.
                existing.role = role
                existing.status = UserStatus.ACTIVE
                existing.full_name = existing.full_name or full_name.strip()
                await session.commit()
                print(f"Promoted existing account {validated} to {role.value}.")
                return 0

            users.add(
                User(
                    role=role,
                    status=UserStatus.ACTIVE,
                    email=validated,
                    full_name=full_name.strip(),
                )
            )
            await session.commit()
    finally:
        await dispose_engine()

    print(f"Granted {role.value} access to {validated}.")
    print("Sign in at /api/v1/auth/google/authorize with that Google account.")
    return 0


async def mint_dev_token(email: str) -> int:
    """Print an access token for an existing account.

    For exercising the API in Swagger UI or curl without running the Google
    redirect by hand each time.

    Deliberately a CLI command and **not** an HTTP endpoint: an endpoint that
    issues tokens is a backdoor whatever it is guarded with, and one
    misconfigured environment variable would expose it. Running this requires
    a shell on the server, which is already full access.

    The account must already exist — this mints a token for an identity, it
    does not create or authorise one.
    """
    settings = get_settings()
    validated = validate_email(email)
    if validated is None:
        print(f"'{email}' is not a valid email address.", file=sys.stderr)
        return 1

    if settings.environment is Environment.PRODUCTION:
        print(
            "WARNING: minting a token against PRODUCTION. "
            "It carries this account's full privileges until it expires.",
            file=sys.stderr,
        )

    create_engine(settings)
    try:
        async with get_sessionmaker()() as session:
            user = await UserRepository(session).by_email(validated)
            if user is None:
                print(
                    f"No account for {validated}. Create one with: python -m app.cli grant-admin",
                    file=sys.stderr,
                )
                return 1
            if user.status is not UserStatus.ACTIVE:
                print(f"{validated} is {user.status.value}.", file=sys.stderr)
                return 1

            token, expires_in = create_access_token(
                settings=settings, user_id=user.id, role=user.role.value
            )
    finally:
        await dispose_engine()

    print(f"# {validated} ({user.role.value}), valid for {expires_in // 60} minutes")
    print(token)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.cli", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    grant = sub.add_parser(
        "grant-admin", help="Grant admin or event-staff access to a Google account"
    )
    grant.add_argument("--email", required=True, help="The person's Google account email")
    grant.add_argument("--name", required=True, help="Full name")
    grant.add_argument(
        "--role",
        default=UserRole.ADMIN.value,
        choices=[UserRole.ADMIN.value, UserRole.EVENT_STAFF.value],
    )

    token = sub.add_parser("dev-token", help="Print an access token for an existing account")
    token.add_argument("--email", required=True)

    args = parser.parse_args(argv)

    if args.command == "grant-admin":
        return asyncio.run(grant_access(args.email, args.name, UserRole(args.role)))
    if args.command == "dev-token":
        return asyncio.run(mint_dev_token(args.email))

    return 1  # pragma: no cover - argparse enforces a known command


if __name__ == "__main__":
    raise SystemExit(main())
