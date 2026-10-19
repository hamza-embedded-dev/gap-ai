from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo


_DATASET_PATH = Path(__file__).resolve().parents[3] / "demo" / "seed" / "demo_plans.json"
_PLAN_FIELDS = {
    "id",
    "title",
    "category",
    "planned_start",
    "planned_end",
    "recurrence_rule",
    "source",
    "created_at",
}
_OUTCOME_FIELDS = {
    "id",
    "plan_id",
    "status",
    "actual_start",
    "postponed_to",
    "note",
    "reported_via",
    "reported_at",
}
_CATEGORIES = {"sport", "study", "work", "meeting", "health", "social", "personal", "other"}
_SOURCES = {"text", "voice", "device"}
_STATUSES = {"done", "postponed", "skipped"}
_REPORTED_VIA = {"web", "device", "auto"}


def materialize_demo_profile(
    user_id: str,
    *,
    profile_id: str = "regular",
    session_started_at: datetime,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Load, validate, shift, and assign fresh database IDs to one seed profile."""
    if session_started_at.tzinfo is None:
        raise ValueError("Demo session timestamp must include a timezone")

    document = json.loads(_DATASET_PATH.read_text(encoding="utf-8"))
    try:
        zone = ZoneInfo(document["timezone"])
        anchor_date = date.fromisoformat(document["anchor_date"])
        profile = document["profiles"][profile_id]
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Demo seed metadata or profile is invalid") from exc

    plans = profile.get("plans")
    outcomes = profile.get("outcomes")
    if not isinstance(plans, list) or not isinstance(outcomes, list):
        raise ValueError("Demo seed profile must contain plan and outcome lists")

    anchor = datetime.combine(anchor_date, time(hour=12), tzinfo=zone).astimezone(timezone.utc)
    delta = session_started_at.astimezone(timezone.utc) - anchor
    plan_ids: dict[str, str] = {}
    shifted_plans: list[dict[str, Any]] = []

    for seed_plan in plans:
        if not isinstance(seed_plan, dict) or set(seed_plan) != _PLAN_FIELDS:
            raise ValueError("Demo seed plan fields do not match the database schema")
        old_id = str(seed_plan["id"])
        if old_id in plan_ids:
            raise ValueError("Demo seed plan IDs must be unique")
        if seed_plan["category"] not in _CATEGORIES or seed_plan["source"] not in _SOURCES:
            raise ValueError("Demo seed plan has an unsupported category or source")
        start = _shift_timestamp(seed_plan["planned_start"], delta, zone)
        end = _shift_timestamp(seed_plan["planned_end"], delta, zone)
        created = _shift_timestamp(seed_plan["created_at"], delta, zone)
        if datetime.fromisoformat(end) <= datetime.fromisoformat(start):
            raise ValueError("Demo seed plan end must be after start")
        if datetime.fromisoformat(created) > datetime.fromisoformat(start):
            raise ValueError("Demo seed plan cannot be created after it starts")

        new_id = str(uuid4())
        plan_ids[old_id] = new_id
        shifted_plans.append(
            {
                "id": new_id,
                "user_id": user_id,
                "title": seed_plan["title"],
                "category": seed_plan["category"],
                "planned_start": start,
                "planned_end": end,
                "recurrence_rule": seed_plan["recurrence_rule"],
                "source": seed_plan["source"],
                "created_at": created,
            }
        )

    shifted_outcomes: list[dict[str, Any]] = []
    for seed_outcome in outcomes:
        if not isinstance(seed_outcome, dict) or set(seed_outcome) != _OUTCOME_FIELDS:
            raise ValueError("Demo seed outcome fields do not match the database schema")
        if seed_outcome["plan_id"] not in plan_ids:
            raise ValueError("Demo seed outcome references an unknown plan")
        if seed_outcome["status"] not in _STATUSES or seed_outcome["reported_via"] not in _REPORTED_VIA:
            raise ValueError("Demo seed outcome has an unsupported status or channel")
        shifted_outcomes.append(
            {
                "plan_id": plan_ids[seed_outcome["plan_id"]],
                "status": seed_outcome["status"],
                "actual_start": _shift_optional_timestamp(seed_outcome["actual_start"], delta, zone),
                "postponed_to": _shift_optional_timestamp(seed_outcome["postponed_to"], delta, zone),
                "note": seed_outcome["note"],
                "reported_via": seed_outcome["reported_via"],
                "reported_at": _shift_timestamp(seed_outcome["reported_at"], delta, zone),
            }
        )

    return shifted_plans, shifted_outcomes


def _shift_optional_timestamp(
    value: str | None, delta: timedelta, zone: ZoneInfo
) -> str | None:
    return None if value is None else _shift_timestamp(value, delta, zone)


def _shift_timestamp(value: str, delta: timedelta, zone: ZoneInfo) -> str:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Demo seed timestamps must be valid ISO-8601 values") from exc
    if parsed.tzinfo is None:
        raise ValueError("Demo seed timestamps must include a timezone")
    return (parsed.astimezone(timezone.utc) + delta).astimezone(zone).isoformat()
