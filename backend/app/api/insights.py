from __future__ import annotations

import inspect
from datetime import datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field

from app.analytics.insights import calculate_insights, calculate_recommendations, get_period_window
from app.api.errors import APIError
from app.api.plans import current_user
from app.api.upcoming import get_system_time
from app.db.plans import AuthenticatedUser, PlanStore, get_plan_store
from app.recommendations import apply_policy

router = APIRouter()


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


class BehaviorRecommendation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    message: str
    why: str
    evidence: dict[str, str | int | float]
    confidence: Literal["moderate", "none"]
    next_step: str
    source: Literal["behavior", "discovery"] = "behavior"
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
    recommendations: list[BehaviorRecommendation] = Field(default_factory=list)


@router.get("/insights", response_model=InsightsResponse)
def get_insights(
    user: AuthenticatedUser = Depends(current_user),
    store: PlanStore = Depends(get_plan_store),
    period: str = Query(default="week"),
    current_time: datetime = Depends(get_system_time),
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
    result["recommendations"] = apply_policy(
        calculate_recommendations(history, outcomes, user_timezone=user.timezone), feedback
    )
    return result
