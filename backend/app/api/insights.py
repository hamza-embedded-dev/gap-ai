from __future__ import annotations

import inspect
import logging
from datetime import datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field

from app.ai.llm import LLMError, NebiusLLMClient, get_llm_client
from app.analytics.insights import calculate_insights, calculate_recommendations, get_period_window
from app.api.errors import APIError
from app.api.plans import current_user
from app.api.upcoming import get_system_time
from app.config import get_settings
from app.db.plans import AuthenticatedUser, PlanStore, get_plan_store
from app.recommendations import apply_policy, build_contextual_recommendations
from app.services.weather import DEFAULT_LATITUDE, DEFAULT_LONGITUDE, WeatherService

router = APIRouter()
logger = logging.getLogger(__name__)


def generate_coaching_narrative(
    llm: NebiusLLMClient | None,
    *,
    metrics: dict[str, Any],
    plans: list[dict[str, Any]],
    outcomes: list[dict[str, Any]],
    user_timezone: str,
    timeout: float | None = None,
) -> str | None:
    """Generate a personalized AI coaching narrative from actual plans, outcomes, and metrics.

    Uses NebiusLLMClient when available and falls back gracefully to a deterministic
    personalized summary upon timeouts, configuration errors, or provider failures.
    """
    planned = metrics.get("planned", 0)
    done = metrics.get("done", 0)
    postponed = metrics.get("postponed", 0)
    skipped = metrics.get("skipped", 0)
    adherence_pct = metrics.get("adherence_pct")

    # Deterministic fallback based on genuine user activity
    if adherence_pct is not None and planned > 0:
        fallback = (
            f"Your plan adherence this period is {adherence_pct:.0f}%, with {done} of {planned} "
            f"activities completed. Keep your momentum going on upcoming plans!"
        )
    elif planned > 0 and done == 0:
        fallback = (
            f"You have {planned} planned {'activities' if planned > 1 else 'activity'} scheduled. "
            "Focus on taking the first step today and log your progress when done."
        )
    elif plans:
        fallback = (
            "You have active plans in your calendar. Stick to your scheduled start times "
            "to begin establishing consistent habits."
        )
    else:
        fallback = (
            "Welcome to your Personal AI Coach! Create your next plan using voice on your ESP32 "
            "or the web app, and track completions to receive personalized habit insights."
        )

    if llm is None:
        return fallback

    upcoming_titles = [str(p.get("title", "")) for p in plans[:3] if p.get("title")]
    prompt_user = (
        f"Period: {metrics.get('period', 'week')}\n"
        f"Planned count: {planned}\n"
        f"Completed: {done}\n"
        f"Postponed: {postponed}\n"
        f"Skipped: {skipped}\n"
        f"Adherence rate: {f'{adherence_pct:.1f}%' if adherence_pct is not None else 'None (no completed tasks yet)'}\n"
        f"Recent plan titles: {', '.join(upcoming_titles) if upcoming_titles else 'None'}\n"
        f"User timezone: {user_timezone}\n"
        "Provide an encouraging 2-sentence personalized coaching reflection and next step."
    )
    messages = [
        {
            "role": "system",
            "content": (
                "You are the GAP-AI Personal AI Coach. Analyze the user's actual plans, "
                "completion rate, and postponed tasks. Provide an encouraging, concise (2 to 3 sentences) "
                "personalized coaching reflection and practical tip. Never invent non-existent history. "
                "Output only the plain narrative text without markdown formatting or bullet points."
            ),
        },
        {"role": "user", "content": prompt_user},
    ]

    resolved_timeout = timeout
    if resolved_timeout is None:
        try:
            resolved_timeout = get_settings().nebius_coaching_timeout_seconds
        except Exception:
            resolved_timeout = 5.0

    try:
        content = llm.complete(
            messages,
            timeout=resolved_timeout,
            temperature=0.3,
            max_retries=0,
        )
        narrative = content.strip().strip('"').strip("'")
        if narrative and len(narrative) <= 500 and "\n\n" not in narrative:
            return narrative
        if narrative:
            return " ".join(line.strip() for line in narrative.splitlines() if line.strip())[:500]
    except Exception as exc:
        logger.warning("Personal AI Coach narrative generation via LLM failed: %s; using fallback", exc)

    return fallback


class WeekdayInsight(BaseModel):
    model_config = ConfigDict(extra="forbid")

    planned: int
    done: int
    postponed: int


class HourInsight(BaseModel):
    model_config = ConfigDict(extra="forbid")

    planned: int
    done: int


class CategoryInsight(BaseModel):
    model_config = ConfigDict(extra="forbid")

    planned: int
    done: int


class PostponedTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    weekday: str
    hour: int
    count: int


class TrendInsight(BaseModel):
    model_config = ConfigDict(extra="forbid")

    adherence_pct_delta: float | None = None


class RecommendationCard(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    message: str
    why: str
    evidence: dict[str, str | int | float]
    confidence: Literal["moderate", "none"]
    next_step: str
    source: Literal["behavior", "discovery", "contextual"] = "behavior"
    label: str | None = None
    dedup_key: str | None = None
    duration_minutes: int | None = Field(default=None, ge=5, le=1440)


class InsightsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    period: Literal["week", "last_week", "all"]
    planned: int
    done: int
    postponed: int
    skipped: int
    unreported: int
    adherence_pct: float | None
    avg_start_delay_min: int | None
    by_weekday: dict[str, WeekdayInsight]
    by_hour: dict[str, HourInsight]
    by_category: dict[str, CategoryInsight]
    postponed_targets: list[PostponedTarget]
    trend_vs_prev: TrendInsight | None
    narrative: str | None
    is_demo: bool
    data_label: Literal["real", "demo"]
    recommendations: list[RecommendationCard] = Field(default_factory=list)


@router.get("/insights", response_model=InsightsResponse)
def get_insights(
    user: AuthenticatedUser = Depends(current_user),
    store: PlanStore = Depends(get_plan_store),
    period: str = Query(default="week"),
    current_time: datetime = Depends(get_system_time),
    llm: NebiusLLMClient | None = Depends(get_llm_client),
) -> dict[str, Any]:
    if period not in ("week", "last_week", "all"):
        raise APIError(
            422,
            "validation_error",
            "Query parameter 'period' must be one of: 'week', 'last_week', 'all'.",
        )

    try:
        user_tz = ZoneInfo(user.timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise APIError(422, "validation_error", "The user's timezone is invalid.") from exc

    list_plans_fn = getattr(store, "list_plans", None)
    if list_plans_fn is None:
        raise NotImplementedError("PlanStore implementation does not support list_plans yet.")

    window_start, window_end = get_period_window(period, current_time, user_tz)

    param_names = set(inspect.signature(list_plans_fn).parameters.keys())
    if "from_time" in param_names:
        plans = list_plans_fn(user_id=user.id, from_time=window_start, to_time=window_end)
    elif "from_" in param_names:
        plans = list_plans_fn(user_id=user.id, from_=window_start, to=window_end)
    else:
        plans = list_plans_fn(user.id, window_start, window_end)

    list_outcomes_fn = getattr(store, "list_outcomes", None)
    if list_outcomes_fn is None:
        raise NotImplementedError("PlanStore implementation does not support list_outcomes yet.")

    outcome_params = set(inspect.signature(list_outcomes_fn).parameters.keys())
    if "user_id" in outcome_params:
        outcomes = list_outcomes_fn(user_id=user.id)
    else:
        outcomes = list_outcomes_fn(user.id)

    result = calculate_insights(
        plans=plans,
        outcomes=outcomes,
        period=period,
        reference_time=current_time,
        user_timezone=user.timezone,
        is_demo=user.is_demo,
    )
    history_fn = getattr(store, "list_plans")
    history = history_fn(user_id=user.id)
    feedback_fn = getattr(store, "list_recommendation_feedback", None)
    feedback = feedback_fn(user.id) if feedback_fn else []
    profile_fn = getattr(store, "get_personalization", None)
    profile = profile_fn(user_id=user.id) if profile_fn else {}

    contextual: list[dict[str, Any]] = []
    weather_forecast = None
    if profile.get("recommendation_frequency") != "off":
        try:
            upcoming = [
                plan for plan in history
                if not plan.get("latest_outcome") and plan.get("planned_start")
                and _as_datetime(plan["planned_start"]) >= current_time
            ]
            if upcoming:
                next_plan = min(upcoming, key=lambda plan: _as_datetime(plan["planned_start"]))
                with WeatherService() as weather_service:
                    weather_forecast = weather_service.get_forecast(
                        latitude=DEFAULT_LATITUDE,
                        longitude=DEFAULT_LONGITUDE,
                        target_time=_as_datetime(next_plan["planned_start"]),
                        timezone_str=user.timezone,
                    )
        except Exception as exc:
            logger.warning("Contextual weather lookup failed: %s", exc)

    from fastapi.params import Depends as DependsClass
    actual_llm: NebiusLLMClient | None = None
    if isinstance(llm, NebiusLLMClient):
        actual_llm = llm
    elif not isinstance(llm, DependsClass) and llm is not None:
        actual_llm = llm
    else:
        try:
            actual_llm = get_llm_client()
        except Exception:
            actual_llm = None

    if profile.get("recommendation_frequency") == "off":
        result["recommendations"] = []
        result["narrative"] = None
    else:
        contextual = build_contextual_recommendations(
            profile=profile,
            plans=history,
            now=current_time,
            timezone_name=user.timezone,
            weather_forecast=weather_forecast,
            outcomes=outcomes,
        )
        result["recommendations"] = apply_policy(
            calculate_recommendations(history, outcomes, user_timezone=user.timezone),
            feedback,
            contextual=contextual,
            now=current_time,
        )
        result["narrative"] = generate_coaching_narrative(
            actual_llm,
            metrics=result,
            plans=history,
            outcomes=outcomes,
            user_timezone=user.timezone,
        )
    return result


def _as_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
