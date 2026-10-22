from __future__ import annotations

import hashlib
import inspect
import json
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Header, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict

from app.config import get_settings
from app.db.plans import AuthenticatedUser, PlanStore, get_plan_store
from app.schemas.parsed_plan import ParsedPlan
from app.system_time import get_system_time

from .errors import APIError

router = APIRouter()
bearer_scheme = HTTPBearer(auto_error=False)


class PlanCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parsed_plan: ParsedPlan
    source: Literal["text", "voice", "device"]


class PlanResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    category: str
    planned_start: datetime
    planned_end: datetime
    recurrence_rule: str | None
    source: Literal["text", "voice", "device"]
    created_at: datetime
    latest_outcome: dict[str, Any] | None


class PlanListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[PlanResponse]


def current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    store: PlanStore = Depends(get_plan_store),
    now: datetime | None = None,
) -> AuthenticatedUser:
    settings = get_settings()
    if credentials is None or settings.token_hash_pepper is None:
        raise APIError(401, "unauthorized", "Token is missing or invalid.")

    raw_token = credentials.credentials
    token_hash = hashlib.sha256(
        (raw_token + settings.token_hash_pepper.get_secret_value()).encode("utf-8")
    ).hexdigest()
    authenticated = store.get_user_for_token_hash(token_hash)
    if authenticated is None:
        raise APIError(401, "unauthorized", "Token is missing or invalid.")

    user, token_expires_at = authenticated
    now = (now or get_system_time()).astimezone(timezone.utc)
    if token_expires_at is not None and _parse_timestamp(token_expires_at) <= now:
        raise APIError(401, "unauthorized", "Token is missing or invalid.")
    if user.is_demo and (
        user.demo_expires_at is None or _parse_timestamp(user.demo_expires_at) <= now
    ):
        raise APIError(401, "unauthorized", "Token is missing or invalid.")
    return user


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Database timestamps must include a timezone.")
    return parsed.astimezone(timezone.utc)


def canonical_request_hash(request: PlanCreateRequest) -> str:
    canonical = json.dumps(
        request.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _plan_values(request: PlanCreateRequest, user: AuthenticatedUser) -> dict[str, Any]:
    parsed_plan = request.parsed_plan.root
    if parsed_plan["intent"] != "create_plan":
        raise APIError(422, "validation_error", "Only create_plan intents can be saved.")
    try:
        zone = ZoneInfo(user.timezone)
    except ZoneInfoNotFoundError as exc:
        raise APIError(422, "validation_error", "The user's timezone is invalid.") from exc

    try:
        plan_date = date.fromisoformat(parsed_plan["date"])
        plan_time = time.fromisoformat(parsed_plan["time"])
    except ValueError as exc:
        raise APIError(422, "validation_error", "The plan date or time is invalid.") from exc
    start = datetime.combine(plan_date, plan_time, tzinfo=zone)
    duration = parsed_plan["duration_minutes"]
    end = start + timedelta(minutes=60 if duration is None else duration)
    return {
        "user_id": user.id,
        "title": parsed_plan["title"],
        "category": parsed_plan["category"],
        "planned_start": start.isoformat(),
        "planned_end": end.isoformat(),
        "recurrence_rule": parsed_plan["recurrence"],
        "source": request.source,
    }


@router.post("/plans", response_model=PlanResponse, status_code=201)
def create_plan(
    payload: PlanCreateRequest,
    user: AuthenticatedUser = Depends(current_user),
    store: PlanStore = Depends(get_plan_store),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", min_length=1),
) -> dict[str, Any]:
    plan = _plan_values(payload, user)
    if idempotency_key is None:
        return store.create_plan(plan)

    snapshot, conflict = store.create_plan_idempotently(
        user_id=user.id,
        idempotency_key=idempotency_key,
        request_hash=canonical_request_hash(payload),
        plan=plan,
    )
    if conflict:
        raise APIError(
            422,
            "validation_error",
            "Idempotency-Key was already used with a different request.",
        )
    return snapshot


@router.get("/plans", response_model=PlanListResponse)
def list_plans(
    user: AuthenticatedUser = Depends(current_user),
    store: PlanStore = Depends(get_plan_store),
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = Query(default=None, alias="to"),
) -> dict[str, Any]:
    list_fn = getattr(store, "list_plans", None)
    if list_fn is None:
        raise NotImplementedError("PlanStore implementation does not support list_plans yet.")

    param_names = set(inspect.signature(list_fn).parameters.keys())
    if "from_time" in param_names:
        items = list_fn(user_id=user.id, from_time=from_, to_time=to)
    elif "from_" in param_names:
        items = list_fn(user_id=user.id, from_=from_, to=to)
    else:
        items = list_fn(user.id, from_, to)
    return {"items": items}
