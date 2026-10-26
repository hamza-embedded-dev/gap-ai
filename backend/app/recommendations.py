"""Deterministic recommendation policy and neutral discovery catalog."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import hashlib
import os
from typing import Any

DISMISSAL_DAYS = 30

DISCOVERY_IDEAS = [
    {"id": "discovery-walk", "title": "Take a short walk", "message": "Try a 15-minute walk as a small reset.", "duration_minutes": 15},
    {"id": "discovery-learn", "title": "Learn one small thing", "message": "Spend 20 minutes exploring a topic you choose.", "duration_minutes": 20},
    {"id": "discovery-project", "title": "Make a tiny project", "message": "Choose a simple idea and build its first small piece.", "duration_minutes": 30},
    {"id": "discovery-break", "title": "Take a healthy break", "message": "Step away for 10 minutes, stretch, and rest your eyes.", "duration_minutes": 10},
    {"id": "discovery-experience", "title": "Try a nearby experience", "message": "Pick a place or activity you have not tried before.", "duration_minutes": 45},
]


def dedup_key(item: dict[str, Any]) -> str:
    """Stable SHA-256 of normalized idea identity; excludes message wording and duration."""
    identity = f"{item.get('source', 'discovery')}:{item.get('id', '')}".strip().lower()
    return hashlib.sha256(identity.encode()).hexdigest()


def build_contextual_recommendations(
    *,
    profile: dict[str, Any],
    plans: list[dict[str, Any]],
    now: datetime,
    timezone_name: str,
    weather_forecast: Any = None,
) -> list[dict[str, Any]]:
    """Build contextual cards only from explicitly stored profile and plan data."""
    from zoneinfo import ZoneInfo

    local_now = now.astimezone(ZoneInfo(timezone_name))
    cards: list[dict[str, Any]] = []
    goals = profile.get("deadlines_goals") or []
    for goal in goals:
        if not isinstance(goal, dict) or not isinstance(goal.get("title"), str):
            continue
        title = goal["title"].strip()
        if not title:
            continue
        kind = goal.get("kind", "goal")
        raw_deadline = goal.get("deadline")
        deadline: date | None = None
        if raw_deadline:
            try:
                deadline = date.fromisoformat(str(raw_deadline))
            except ValueError:
                continue
            if deadline < local_now.date():
                continue
        if deadline is None and kind != "goal":
            continue

        kind_label = {"exam": "exam date", "deadline": "deadline", "goal": "goal"}.get(kind, "goal")
        identity = hashlib.sha256(f"{kind}:{title.casefold()}:{deadline or ''}".encode()).hexdigest()[:16]
        date_basis = f" on {deadline.isoformat()}" if deadline else ""
        availability = next((v.strip() for v in (profile.get("typical_availability") or []) if isinstance(v, str) and v.strip()), None)
        next_step = f"Check the availability you entered: {availability}." if availability else "Choose a time that works for you and review it in My Plans."
        cards.append({
            "id": f"context-goal-{identity}",
            "title": f"Plan around your {kind_label}",
            "message": f"You entered “{title}”{date_basis}. Review your next step before then." if deadline else f"You entered “{title}” as a goal. Choose one next step when you are ready.",
            "why": f"Based on the {kind_label} you entered{date_basis}.",
            "evidence": {"kind": kind, **({"deadline": deadline.isoformat()} if deadline else {}), "goal_title": title},
            "confidence": "moderate",
            "next_step": next_step,
            "source": "contextual",
            "label": f"Based on the {kind_label} you entered",
        })

    upcoming: list[dict[str, Any]] = []
    for plan in plans:
        if not plan.get("planned_start") or plan.get("latest_outcome"):
            continue
        try:
            start = plan["planned_start"] if isinstance(plan["planned_start"], datetime) else datetime.fromisoformat(str(plan["planned_start"]).replace("Z", "+00:00"))
            if start.tzinfo is None:
                continue
            start = start.astimezone(local_now.tzinfo)
        except (TypeError, ValueError):
            continue
        if start >= local_now:
            upcoming.append({**plan, "_context_start": start})
    upcoming.sort(key=lambda item: item["_context_start"])
    if upcoming:
        plan = upcoming[0]
        start = plan["_context_start"]
        plan_id = str(plan.get("id", ""))
        plan_title = str(plan.get("title", "Plan"))
        cards.append({
            "id": f"context-plan-{plan_id}",
            "title": "Your next planned activity",
            "message": f"“{plan_title}” is scheduled for {start.strftime('%Y-%m-%d %H:%M %Z')}. Check that it still fits your day.",
            "why": "Based on your upcoming plan.",
            "evidence": {"plan_id": plan_id, "planned_start": start.isoformat(), "plan_title": plan_title},
            "confidence": "moderate",
            "next_step": "Review this plan in My Plans; confirm before changing its time.",
            "source": "contextual",
            "label": "Based on your upcoming plan",
        })
        if weather_forecast is not None and getattr(weather_forecast, "is_rainy", False):
            probability = getattr(weather_forecast, "precipitation_probability", None)
            evidence: dict[str, str | int | float] = {
                "plan_id": plan_id,
                "planned_start": start.isoformat(),
                "forecast_area": "Üsküdar app default; not a saved user location",
                "weather_code": getattr(weather_forecast, "weather_code", None) or "rain",
            }
            if probability is not None:
                evidence["precipitation_probability"] = probability
            cards.append({
                "id": f"context-weather-{plan_id}",
                "title": "Check the forecast for your plan",
                "message": f"Rain is forecast near “{plan_title}” at the app’s default Üsküdar location. Check the forecast before deciding what to do.",
                "why": "Based on the existing weather service and its fixed Üsküdar app default, not a location saved for you.",
                "evidence": evidence,
                "confidence": "moderate",
                "next_step": "Review the forecast in My Plans; confirm before changing the plan.",
                "source": "contextual",
                "label": "Weather context · app default location",
            })

    availability = [v.strip() for v in (profile.get("typical_availability") or []) if isinstance(v, str) and v.strip()]
    if availability:
        slot = availability[0]
        cards.append({
            "id": f"context-availability-{hashlib.sha256(slot.casefold().encode()).hexdigest()[:16]}",
            "title": "Use the availability you shared",
            "message": f"You said you are typically available: “{slot}”. Choose what, if anything, you want to plan for that time.",
            "why": "Based on your stated availability.",
            "evidence": {"typical_availability": slot},
            "confidence": "moderate",
            "next_step": "Review your availability and create a plan only if it suits you.",
            "source": "contextual",
            "label": "Based on your stated availability",
        })
    return cards


def apply_policy(
    behavior: list[dict[str, Any]],
    feedback: list[dict[str, Any]],
    *,
    contextual: list[dict[str, Any]] | None = None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    now = now or datetime.now(timezone.utc)
    try:
        behavior_slots = max(0, min(3, int(os.getenv("RECOMMENDATION_BEHAVIOR_SLOTS", "1"))))
    except ValueError:
        behavior_slots = 1
    try:
        contextual_slots = max(0, min(3 - behavior_slots, int(os.getenv("RECOMMENDATION_CONTEXTUAL_SLOTS", "1"))))
    except ValueError:
        contextual_slots = 1
    discovery_slots = 3 - behavior_slots - contextual_slots
    hidden: set[str] = set()
    expired_dismissals: set[str] = set()
    useful = set()
    not_useful = set()
    for entry in feedback:
        rid = entry.get("recommendation_id")
        if entry.get("action") == "dismissed":
            try:
                created = datetime.fromisoformat(str(entry["created_at"]).replace("Z", "+00:00"))
            except (KeyError, ValueError):
                continue
            if created > now - timedelta(days=DISMISSAL_DAYS):
                hidden.add(rid)
            else:
                expired_dismissals.add(rid)
        if entry.get("rating") == "useful":
            useful.add(rid)
        elif entry.get("rating") == "not_useful":
            not_useful.add(rid)
    behavior = [dict(r, source="behavior", label=None) for r in behavior if r["id"] not in hidden]
    contextual = [dict(r, source="contextual") for r in (contextual or []) if r["id"] not in hidden]
    discovery = [dict(i, source="discovery", label="Not based on your history", why="Starter idea; not based on your history.", confidence="none", evidence={}, next_step=i["message"]) for i in DISCOVERY_IDEAS if i["id"] not in hidden]
    # Persisted useful feedback affects selection: positively rated ideas are prioritized.
    rank = lambda r: (r["id"] not in useful, r["id"] not in expired_dismissals, r["id"] in not_useful, r["id"])
    behavior.sort(key=rank)
    contextual.sort(key=rank)
    discovery.sort(key=rank)
    chosen = behavior[:behavior_slots]
    chosen.extend(contextual[:contextual_slots])
    chosen.extend(discovery[:discovery_slots])
    # Fill unused slots from either pool while preserving the default balance when possible.
    used = {item["id"] for item in chosen}
    chosen.extend([r for r in behavior + contextual + discovery if r["id"] not in used][:3-len(chosen)])
    for item in chosen:
        item["dedup_key"] = dedup_key(item)
    return chosen[:3]
