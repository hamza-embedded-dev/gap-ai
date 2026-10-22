"""Issue a bearer token for a real (non-demo) user, e.g. an ESP32 device or a test user.

There is no public sign-up endpoint (K-2); tokens are provisioned with this admin
script. Run it from the `backend/` directory so `app` is importable:

    uv run python -m scripts.create_access_token --display-name "ESP32 Ahmet"
    uv run python -m scripts.create_access_token --user-id <uuid> --expires-days 30

The raw token is printed to stdout exactly once and is never stored. The database
only receives sha256(token + TOKEN_HASH_PEPPER), the same digest that
`app.api.plans.current_user` checks (D-002). Status messages go to stderr, so
`TOKEN=$(uv run python -m scripts.create_access_token ...)` captures only the token.
"""

from __future__ import annotations

import argparse
import hashlib
import secrets
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urljoin
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

from app.config import get_settings

DEFAULT_TIMEZONE = "Europe/Istanbul"


class TokenIssueError(Exception):
    """A user-facing failure; the message is safe to print."""


@dataclass(frozen=True)
class IssuedToken:
    user_id: str
    display_name: str | None
    token: str
    expires_at: datetime | None


def hash_token(raw_token: str, pepper: str) -> str:
    return hashlib.sha256((raw_token + pepper).encode("utf-8")).hexdigest()


class TokenAdmin:
    """Service-role PostgREST calls needed to provision a token."""

    def __init__(
        self,
        supabase_url: str,
        service_key: str,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._rest_url = supabase_url.rstrip("/") + "/rest/v1/"
        self._client = httpx.Client(
            headers={
                "apikey": service_key,
                "Authorization": f"Bearer {service_key}",
                "Content-Type": "application/json",
            },
            timeout=10.0,
            transport=transport,
        )

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        response = self._client.get(
            urljoin(self._rest_url, "users"),
            params={
                "select": "id,display_name,is_demo",
                "id": f"eq.{user_id}",
                "limit": "1",
            },
        )
        response.raise_for_status()
        users = response.json()
        return users[0] if users else None

    def create_user(self, display_name: str, timezone_name: str) -> dict[str, Any]:
        response = self._client.post(
            urljoin(self._rest_url, "users"),
            params={"select": "id,display_name,is_demo"},
            headers={"Prefer": "return=representation"},
            json={"display_name": display_name, "timezone": timezone_name},
        )
        response.raise_for_status()
        return response.json()[0]

    def delete_user(self, user_id: str) -> None:
        response = self._client.delete(
            urljoin(self._rest_url, "users"),
            params={"id": f"eq.{user_id}"},
        )
        response.raise_for_status()

    def insert_token(self, user_id: str, token_hash: str, expires_at: datetime | None) -> None:
        response = self._client.post(
            urljoin(self._rest_url, "access_tokens"),
            headers={"Prefer": "return=minimal"},
            json={
                "user_id": user_id,
                "token_hash": token_hash,
                "expires_at": expires_at.isoformat() if expires_at else None,
            },
        )
        response.raise_for_status()


def issue_token(
    admin: TokenAdmin,
    *,
    pepper: str,
    user_id: str | None = None,
    display_name: str | None = None,
    timezone_name: str = DEFAULT_TIMEZONE,
    expires_at: datetime | None = None,
    generate_token: Callable[[], str] = lambda: secrets.token_urlsafe(32),
) -> IssuedToken:
    """Create a token for an existing user, or for a new user when `user_id` is None."""
    created_user = False
    if user_id is not None:
        user = admin.get_user(user_id)
        if user is None:
            raise TokenIssueError(f"User {user_id} does not exist.")
        if user["is_demo"]:
            raise TokenIssueError(
                "Demo users get their tokens from POST /demo/session; refusing to issue one."
            )
    else:
        if not display_name:
            raise TokenIssueError("A display name is required to create a new user.")
        user = admin.create_user(display_name, timezone_name)
        created_user = True

    raw_token = generate_token()
    try:
        admin.insert_token(user["id"], hash_token(raw_token, pepper), expires_at)
    except Exception:
        # Do not leave a user behind that nobody can log in as. Cleanup is
        # best effort; the original error is the one worth reporting.
        if created_user:
            try:
                admin.delete_user(user["id"])
            except httpx.HTTPError:
                pass
        raise

    return IssuedToken(
        user_id=user["id"],
        display_name=user.get("display_name"),
        token=raw_token,
        expires_at=expires_at,
    )


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.create_access_token",
        description="Issue a bearer token for a non-demo user. The token is shown once.",
    )
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--user-id", help="Existing user's UUID")
    target.add_argument("--display-name", help="Create a new user with this name")
    parser.add_argument(
        "--timezone",
        default=DEFAULT_TIMEZONE,
        help=f"IANA timezone for a new user (default: {DEFAULT_TIMEZONE})",
    )
    parser.add_argument(
        "--expires-days",
        type=int,
        help="Token lifetime in days (default: no expiry, valid until revoked)",
    )
    args = parser.parse_args(argv)

    if args.user_id is not None:
        try:
            args.user_id = str(UUID(args.user_id))
        except ValueError:
            parser.error("--user-id must be a UUID")
        if args.timezone != DEFAULT_TIMEZONE:
            parser.error("--timezone only applies when creating a new user")
    try:
        ZoneInfo(args.timezone)
    except (ZoneInfoNotFoundError, ValueError):
        parser.error(f"unknown IANA timezone: {args.timezone}")
    if args.expires_days is not None and args.expires_days <= 0:
        parser.error("--expires-days must be a positive number")
    return args


def _http_error_message(exc: httpx.HTTPStatusError) -> str:
    try:
        detail = exc.response.json().get("message")
    except (ValueError, AttributeError):
        detail = None
    return f"Supabase returned HTTP {exc.response.status_code}" + (f": {detail}" if detail else "")


def main(
    argv: list[str] | None = None,
    *,
    settings: Any = None,
    transport: httpx.BaseTransport | None = None,
) -> int:
    args = _parse_args(argv)
    settings = settings or get_settings()

    pepper = settings.token_hash_pepper.get_secret_value() if settings.token_hash_pepper else ""
    service_key = (
        settings.supabase_service_key.get_secret_value() if settings.supabase_service_key else ""
    )
    if not pepper:
        print("error: TOKEN_HASH_PEPPER is not set", file=sys.stderr)
        return 1
    if not settings.supabase_url or not service_key:
        print("error: SUPABASE_URL and SUPABASE_SERVICE_KEY must be set", file=sys.stderr)
        return 1

    expires_at = None
    if args.expires_days is not None:
        expires_at = datetime.now(timezone.utc) + timedelta(days=args.expires_days)

    admin = TokenAdmin(settings.supabase_url, service_key, transport=transport)
    try:
        issued = issue_token(
            admin,
            pepper=pepper,
            user_id=args.user_id,
            display_name=args.display_name,
            timezone_name=args.timezone,
            expires_at=expires_at,
        )
    except TokenIssueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except httpx.HTTPStatusError as exc:
        print(f"error: {_http_error_message(exc)}", file=sys.stderr)
        return 1
    except httpx.RequestError as exc:
        print(f"error: could not reach Supabase ({type(exc).__name__})", file=sys.stderr)
        return 1

    name = f" ({issued.display_name})" if issued.display_name else ""
    expiry = issued.expires_at.isoformat() if issued.expires_at else "never (valid until revoked)"
    print(f"User:    {issued.user_id}{name}", file=sys.stderr)
    print(f"Expires: {expiry}", file=sys.stderr)
    print("Token (shown once, not stored anywhere):", file=sys.stderr)
    print(issued.token)
    return 0


if __name__ == "__main__":
    sys.exit(main())
