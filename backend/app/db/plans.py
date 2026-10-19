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
    display_name: str | None = None


class PlanStore(Protocol):
    def get_user_for_token_hash(
        self, token_hash: str
    ) -> tuple[AuthenticatedUser, str | None] | None: ...

    def update_profile(
        self, *, user_id: str, changes: dict[str, Any]
    ) -> dict[str, Any] | None: ...

    def create_plan(self, plan: dict[str, Any]) -> dict[str, Any]: ...

    def list_plans(
        self,
        *,
        user_id: str,
        from_time: datetime | None = None,
        to_time: datetime | None = None,
    ) -> list[dict[str, Any]]: ...

    def get_plan(self, *, user_id: str, plan_id: str) -> dict[str, Any] | None: ...

    def create_outcome(
        self, *, user_id: str, plan_id: str, outcome: dict[str, Any]
    ) -> dict[str, Any]: ...

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

    def get_suggestion(self, user_id: str, plan_id: str) -> dict[str, Any] | None: ...

    def save_suggestion(
        self, user_id: str, plan_id: str, suggestion_data: dict[str, Any]
    ) -> dict[str, Any]: ...


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
                "select": "id,display_name,timezone,is_demo,demo_expires_at",
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
            display_name=user.get("display_name"),
        ), token["expires_at"]

    def update_profile(
        self, *, user_id: str, changes: dict[str, Any]
    ) -> dict[str, Any] | None:
        if not changes:
            raise ValueError("Profile update requires at least one field")
        response = self._client.patch(
            urljoin(self._rest_url, "users"),
            params={
                "select": "id,display_name,timezone,is_demo",
                "id": f"eq.{user_id}",
            },
            headers={"Prefer": "return=representation"},
            json=changes,
        )
        response.raise_for_status()
        rows = response.json()
        return rows[0] if rows else None

    def create_plan(self, plan: dict[str, Any]) -> dict[str, Any]:
        response = self._client.post(
            urljoin(self._rest_url, "plans"),
            params={"select": "id,title,category,planned_start,planned_end,recurrence_rule,source,created_at"},
            headers={"Prefer": "return=representation"},
            json=plan,
        )
        response.raise_for_status()
        return _plan_response(response.json()[0])

    def list_plans(
        self,
        *,
        user_id: str,
        from_time: datetime | None = None,
        to_time: datetime | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, str] = {
            "select": PLAN_LIST_FIELDS,
            "user_id": f"eq.{user_id}",
            "order": "planned_start.asc,id.asc",
            "outcomes.order": "reported_at.desc,id.desc",
            "outcomes.limit": "1",
        }
        if from_time is not None and to_time is not None:
            params["and"] = (
                f"(planned_start.gte.{_timestamp(from_time)},"
                f"planned_start.lte.{_timestamp(to_time)})"
            )
        elif from_time is not None:
            params["planned_start"] = f"gte.{_timestamp(from_time)}"
        elif to_time is not None:
            params["planned_start"] = f"lte.{_timestamp(to_time)}"
        response = self._client.get(urljoin(self._rest_url, "plans"), params=params)
        response.raise_for_status()
        return [_plan_list_response(row) for row in response.json()]

    def get_plan(self, *, user_id: str, plan_id: str) -> dict[str, Any] | None:
        response = self._client.get(
            urljoin(self._rest_url, "plans"),
            params={
                "select": "id,user_id,title,category,planned_start,planned_end,recurrence_rule,source,created_at",
                "id": f"eq.{plan_id}",
                "user_id": f"eq.{user_id}",
                "limit": "1",
            },
        )
        response.raise_for_status()
        rows = response.json()
        return rows[0] if rows else None

    def create_outcome(
        self, *, user_id: str, plan_id: str, outcome: dict[str, Any]
    ) -> dict[str, Any]:
        # Ownership and parent identity are controlled by the authenticated
        # request arguments, never by fields supplied in the event payload.
        body = {
            "user_id": user_id,
            "plan_id": plan_id,
            "status": outcome["status"],
            "actual_start": outcome.get("actual_start"),
            "postponed_to": outcome.get("postponed_to"),
            "note": outcome.get("note"),
            "reported_via": outcome["reported_via"],
        }
        response = self._client.post(
            urljoin(self._rest_url, "outcomes"),
            params={"select": OUTCOME_FIELDS},
            headers={"Prefer": "return=representation"},
            json=body,
        )
        response.raise_for_status()
        rows = response.json()
        if not rows:
            raise RuntimeError("Outcome insert returned no representation")
        return rows[0]

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
            params={"select": "id,display_name,timezone,is_demo,demo_expires_at"},
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
            display_name=user.get("display_name"),
        )

    def get_suggestion(self, user_id: str, plan_id: str) -> dict[str, Any] | None:
        response = self._client.get(
            urljoin(self._rest_url, "suggestions"),
            params={
                "select": SUGGESTION_FIELDS,
                "user_id": f"eq.{user_id}",
                "plan_id": f"eq.{plan_id}",
                "limit": "1",
            },
        )
        response.raise_for_status()
        rows = response.json()
        return rows[0] if rows else None

    def save_suggestion(
        self, user_id: str, plan_id: str, suggestion_data: dict[str, Any]
    ) -> dict[str, Any]:
        """Store the plan's first suggestion and return it.

        Suggestions are never refreshed (MVP), so if one already exists, for
        example from a concurrent first request, that stored one is returned.
        """
        response = self._client.post(
            urljoin(self._rest_url, "suggestions"),
            params={"select": SUGGESTION_FIELDS, "on_conflict": "plan_id"},
            headers={"Prefer": "return=representation,resolution=ignore-duplicates"},
            json=_suggestion_row(user_id, plan_id, suggestion_data),
        )
        response.raise_for_status()
        rows = response.json()
        if rows:
            return rows[0]
        existing = self.get_suggestion(user_id, plan_id)
        if existing is None:
            raise RuntimeError("Suggestion insert was ignored but no stored suggestion was found")
        return existing


SUGGESTION_FIELDS = "plan_id,reason,message,proposed_start,proposed_end,evidence"
OUTCOME_FIELDS = "id,plan_id,user_id,status,actual_start,postponed_to,note,reported_via,reported_at"
LATEST_OUTCOME_FIELDS = "id,status,actual_start,postponed_to,note,reported_via,reported_at"
PLAN_LIST_FIELDS = (
    "id,title,category,planned_start,planned_end,recurrence_rule,source,created_at,"
    f"outcomes({LATEST_OUTCOME_FIELDS})"
)


def _plan_list_response(row: dict[str, Any]) -> dict[str, Any]:
    outcomes = row.pop("outcomes", [])
    return {**row, "latest_outcome": outcomes[0] if outcomes else None}


def _suggestion_row(
    user_id: str, plan_id: str, suggestion_data: dict[str, Any]
) -> dict[str, Any]:
    # Ownership comes only from the arguments; any user_id in the data is ignored.
    if str(suggestion_data.get("plan_id", plan_id)) != plan_id:
        raise ValueError("suggestion_data.plan_id does not match plan_id")
    return {
        "user_id": user_id,
        "plan_id": plan_id,
        "reason": suggestion_data["reason"],
        "message": suggestion_data["message"],
        "proposed_start": _timestamp(suggestion_data["proposed_start"]),
        "proposed_end": _timestamp(suggestion_data["proposed_end"]),
        "evidence": suggestion_data.get("evidence") or {},
    }


def _timestamp(value: datetime | str) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("Suggestion timestamps must include a timezone")
        return value.isoformat()
    return value


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

    def update_profile(
        self, *, user_id: str, changes: dict[str, Any]
    ) -> dict[str, Any] | None:
        return _build_plan_store().update_profile(user_id=user_id, changes=changes)

    def create_plan(self, plan: dict[str, Any]) -> dict[str, Any]:
        return _build_plan_store().create_plan(plan)

    def list_plans(
        self,
        *,
        user_id: str,
        from_time: datetime | None = None,
        to_time: datetime | None = None,
    ) -> list[dict[str, Any]]:
        return _build_plan_store().list_plans(
            user_id=user_id, from_time=from_time, to_time=to_time
        )

    def get_plan(self, *, user_id: str, plan_id: str) -> dict[str, Any] | None:
        return _build_plan_store().get_plan(user_id=user_id, plan_id=plan_id)

    def create_outcome(
        self, *, user_id: str, plan_id: str, outcome: dict[str, Any]
    ) -> dict[str, Any]:
        return _build_plan_store().create_outcome(
            user_id=user_id, plan_id=plan_id, outcome=outcome
        )

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

    def get_suggestion(self, user_id: str, plan_id: str) -> dict[str, Any] | None:
        return _build_plan_store().get_suggestion(user_id, plan_id)

    def save_suggestion(
        self, user_id: str, plan_id: str, suggestion_data: dict[str, Any]
    ) -> dict[str, Any]:
        return _build_plan_store().save_suggestion(user_id, plan_id, suggestion_data)


@lru_cache(maxsize=1)
def get_plan_store() -> PlanStore:
    return LazyPlanStore()
