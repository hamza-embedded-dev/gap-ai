from __future__ import annotations

import inspect
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict

from app.api.errors import APIError
from app.api.plans import current_user
from app.db.plans import AuthenticatedUser, PlanStore, get_plan_store

router = APIRouter()


class UpcomingItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_id: str
    title: str
    planned_start: datetime
    reminder_at: datetime


class UpcomingResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[UpcomingItem]


def get_system_time() -> datetime:
    return datetime.now(timezone.utc)


def _parse_timestamp(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("Timestamp must include a timezone.")
        return value
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Timestamp must include a timezone.")
    return parsed


@router.get("/me/upcoming", response_model=UpcomingResponse)
def get_upcoming(
    user: AuthenticatedUser = Depends(current_user),
    store: PlanStore = Depends(get_plan_store),
    since: datetime | None = Query(default=None),
    to: datetime | None = Query(default=None),
    current_time: datetime = Depends(get_system_time),
) -> dict[str, Any]:
    try:
        user_tz = ZoneInfo(user.timezone)
    except ZoneInfoNotFoundError as exc:
        raise APIError(422, "validation_error", "The user's timezone is invalid.") from exc

    since_val = since if isinstance(since, datetime) else None
    to_val = to if isinstance(to, datetime) else None

    if since_val is not None:
        effective_since = (
            since_val.replace(tzinfo=user_tz) if since_val.tzinfo is None else since_val
        )
    else:
        effective_since = (
            current_time.astimezone(user_tz)
            if current_time.tzinfo
            else current_time.replace(tzinfo=user_tz)
        )

    if to_val is not None:
        effective_to = (
            to_val.replace(tzinfo=user_tz) if to_val.tzinfo is None else to_val
        )
    else:
        effective_to = effective_since + timedelta(hours=24)

    if effective_since > effective_to:
        raise APIError(422, "validation_error", "Parameter 'since' cannot be after 'to'.")

    list_fn = getattr(store, "list_plans", None)
    if list_fn is None:
        raise NotImplementedError("PlanStore implementation does not support list_plans yet.")

    param_names = set(inspect.signature(list_fn).parameters.keys())
    if "from_time" in param_names:
        plans = list_fn(user_id=user.id, from_time=effective_since, to_time=effective_to)
    elif "from_" in param_names:
        plans = list_fn(user_id=user.id, from_=effective_since, to=effective_to)
    else:
        plans = list_fn(user.id, effective_since, effective_to)

    upcoming_items: list[dict[str, Any]] = []
    for plan in plans:
        raw_start = plan["planned_start"]
        start_dt = _parse_timestamp(raw_start).astimezone(user_tz)

        if start_dt < effective_since or start_dt > effective_to:
            continue

        reminder_dt = start_dt - timedelta(minutes=15)
        upcoming_items.append(
            {
                "plan_id": str(plan["id"]),
                "title": plan["title"],
                "planned_start": start_dt,
                "reminder_at": reminder_dt,
            }
        )

    upcoming_items.sort(key=lambda item: item["planned_start"])
    return {"items": upcoming_items}
