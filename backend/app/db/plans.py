from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from typing import Any, Protocol
from urllib.parse import urljoin

import httpx

from app.config import get_settings


@dataclass(frozen=True)
class AuthenticatedUser:
    id: str
    timezone: str
    is_demo: bool
    demo_expires_at: str | None


class PlanStore(Protocol):
    def get_user_for_token_hash(
        self, token_hash: str
    ) -> tuple[AuthenticatedUser, str | None] | None: ...

    def create_plan(self, plan: dict[str, Any]) -> dict[str, Any]: ...

    def create_plan_idempotently(
        self,
        *,
        user_id: str,
        idempotency_key: str,
        request_hash: str,
        plan: dict[str, Any],
    ) -> tuple[dict[str, Any], bool]: ...

    def create_demo_session(
        self,
        *,
        token_hash: str,
        created_at: datetime,
        expires_at: datetime,
    ) -> AuthenticatedUser: ...


class SupabasePlanStore:
    """Small PostgREST adapter; idempotent writes use one transactional RPC."""

    def __init__(self, url: str, service_key: str) -> None:
        self._rest_url = url.rstrip("/") + "/rest/v1/"
        self._client = httpx.Client(
            headers={
                "apikey": service_key,
                "Authorization": f"Bearer {service_key}",
                "Content-Type": "application/json",
            },
            timeout=10.0,
        )

    def get_user_for_token_hash(
        self, token_hash: str
    ) -> tuple[AuthenticatedUser, str | None] | None:
        token_response = self._client.get(
            urljoin(self._rest_url, "access_tokens"),
            params={
                "select": "user_id,expires_at,revoked_at",
                "token_hash": f"eq.{token_hash}",
                "limit": "1",
            },
        )
        token_response.raise_for_status()
        tokens = token_response.json()
        if not tokens or tokens[0]["revoked_at"] is not None:
            return None
        token = tokens[0]

        user_response = self._client.get(
            urljoin(self._rest_url, "users"),
            params={
                "select": "id,timezone,is_demo,demo_expires_at",
                "id": f"eq.{token['user_id']}",
                "limit": "1",
            },
        )
        user_response.raise_for_status()
        users = user_response.json()
        if not users:
            return None
        user = users[0]
        return AuthenticatedUser(
            id=user["id"],
            timezone=user["timezone"],
            is_demo=user["is_demo"],
            demo_expires_at=user["demo_expires_at"],
        ), token["expires_at"]

    def create_plan(self, plan: dict[str, Any]) -> dict[str, Any]:
        response = self._client.post(
            urljoin(self._rest_url, "plans"),
            params={"select": "id,title,category,planned_start,planned_end,recurrence_rule,source,created_at"},
            headers={"Prefer": "return=representation"},
            json=plan,
        )
        response.raise_for_status()
        return _plan_response(response.json()[0])

    def create_plan_idempotently(
        self,
        *,
        user_id: str,
        idempotency_key: str,
        request_hash: str,
        plan: dict[str, Any],
    ) -> tuple[dict[str, Any], bool]:
        rpc_url = urljoin(self._rest_url, "rpc/create_plan_idempotently")
        rpc_args = {
            "p_user_id": user_id,
            "p_idempotency_key": idempotency_key,
            "p_request_hash": request_hash,
            "p_title": plan["title"],
            "p_category": plan["category"],
            "p_planned_start": plan["planned_start"],
            "p_planned_end": plan["planned_end"],
            "p_recurrence_rule": plan["recurrence_rule"],
            "p_source": plan["source"],
        }
        retryable_sqlstates = {"23505", "40001", "40P01"}
        for attempt in range(3):
            response = self._client.post(rpc_url, json=rpc_args)
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                try:
                    sqlstate = exc.response.json().get("code")
                except (ValueError, AttributeError):
                    sqlstate = None
                if sqlstate not in retryable_sqlstates or attempt == 2:
                    raise
                continue
            break
        result = response.json()
        if result["conflict"]:
            return result["response_snapshot"], True
        return result["response_snapshot"], False

    def create_demo_session(
        self,
        *,
        token_hash: str,
        created_at: datetime,
        expires_at: datetime,
    ) -> AuthenticatedUser:
        created_iso = created_at.isoformat()
        expires_iso = expires_at.isoformat()
        user_response = self._client.post(
            urljoin(self._rest_url, "users"),
            params={"select": "id,timezone,is_demo,demo_expires_at"},
            headers={"Prefer": "return=representation"},
            json={
                "display_name": "Demo User",
                "timezone": "Europe/Istanbul",
                "is_demo": True,
                "created_at": created_iso,
                "demo_expires_at": expires_iso,
            },
        )
        user_response.raise_for_status()
        users = user_response.json()
        if not users:
            raise RuntimeError("Failed to create demo user")
        user = users[0]

        token_response = self._client.post(
            urljoin(self._rest_url, "access_tokens"),
            params={"select": "id"},
            headers={"Prefer": "return=representation"},
            json={
                "user_id": user["id"],
                "token_hash": token_hash,
                "created_at": created_iso,
                "expires_at": user["demo_expires_at"],
            },
        )
        token_response.raise_for_status()

        return AuthenticatedUser(
            id=user["id"],
            timezone=user["timezone"],
            is_demo=user["is_demo"],
            demo_expires_at=user["demo_expires_at"],
        )


def _plan_response(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "title": row["title"],
        "category": row["category"],
        "planned_start": row["planned_start"],
        "planned_end": row["planned_end"],
        "recurrence_rule": row["recurrence_rule"],
        "source": row["source"],
        "created_at": row["created_at"],
        "latest_outcome": None,
    }


@lru_cache(maxsize=1)
def _build_plan_store() -> PlanStore:
    settings = get_settings()
    url = settings.supabase_url
    key = settings.supabase_service_key.get_secret_value() if settings.supabase_service_key else None
    if not url or not key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_KEY must be configured")
    return SupabasePlanStore(url, key)


class LazyPlanStore:
    """Defers Supabase configuration checks until the store is actually used.

    Dependency resolution must not fail before authentication checks (missing
    header or pepper) can return their contract 401 responses.
    """

    def get_user_for_token_hash(
        self, token_hash: str
    ) -> tuple[AuthenticatedUser, str | None] | None:
        return _build_plan_store().get_user_for_token_hash(token_hash)

    def create_plan(self, plan: dict[str, Any]) -> dict[str, Any]:
        return _build_plan_store().create_plan(plan)

    def create_plan_idempotently(
        self,
        *,
        user_id: str,
        idempotency_key: str,
        request_hash: str,
        plan: dict[str, Any],
    ) -> tuple[dict[str, Any], bool]:
        return _build_plan_store().create_plan_idempotently(
            user_id=user_id,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            plan=plan,
        )

    def create_demo_session(
        self,
        *,
        token_hash: str,
        created_at: datetime,
        expires_at: datetime,
    ) -> AuthenticatedUser:
        return _build_plan_store().create_demo_session(
            token_hash=token_hash,
            created_at=created_at,
            expires_at=expires_at,
        )


@lru_cache(maxsize=1)
def get_plan_store() -> PlanStore:
    return LazyPlanStore()
