from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from app.ai.llm import LLMError, NebiusLLMClient, get_llm_client
from app.api.errors import APIError
from app.api.plans import current_user
from app.db.plans import AuthenticatedUser, PlanStore, get_plan_store
from app.services.weather import WeatherService

logger = logging.getLogger(__name__)

router = APIRouter()


class SuggestionEvidence(BaseModel):
    model_config = ConfigDict(extra="allow")

    forecast: str | None = None
    adherence_pct: float | None = None
    outcome_count: int | None = None


class SuggestionDetails(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_id: str
    reason: Literal["weather", "pattern"]
    message: str = Field(min_length=1, max_length=240)
    proposed_start: datetime
    proposed_end: datetime
    evidence: SuggestionEvidence | dict[str, Any]

    @field_validator("message")
    @classmethod
    def message_must_be_single_line(cls, value: str) -> str:
        if "\n" in value or "\r" in value:
            raise ValueError("suggestion message must be a single line")
        return value

    @field_serializer("evidence")
    def serialize_evidence(
        self, evidence: SuggestionEvidence | dict[str, Any]
    ) -> dict[str, Any]:
        if isinstance(evidence, SuggestionEvidence):
            return evidence.model_dump(exclude_none=True)
        return evidence


class SuggestionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    suggestion: SuggestionDetails | None


def _plan_not_found() -> APIError:
    return APIError(404, "not_found", "Plan not found.")


def _parse_iso(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _calculate_adherence_pct(plans: list[dict[str, Any]], now: datetime) -> float | None:
    """Calculate adherence percentage for past plans having reported outcomes.

    adherence_pct = done / (done + postponed + skipped)
    Unreported past plans are excluded from denominator.
    Returns None if no past plan with reported outcome exists.
    """
    done_count = 0
    reported_count = 0

    for p in plans:
        planned_end = _parse_iso(p["planned_end"])
        if planned_end > now:
            continue

        outcome = p.get("latest_outcome")
        if not outcome:
            continue

        status = outcome.get("status")
        if status in ("done", "postponed", "skipped"):
            reported_count += 1
            if status == "done":
                done_count += 1

    if reported_count == 0:
        return None

    return round((done_count / reported_count) * 100.0, 1)


def _reported_plan_count(plans: list[dict[str, Any]], now: datetime) -> int:
    return sum(
        1
        for plan in plans
        if _parse_iso(plan["planned_end"]) <= now
        and (plan.get("latest_outcome") or {}).get("status")
        in ("done", "postponed", "skipped")
    )


def _generate_suggestion_message(
    llm: NebiusLLMClient,
    *,
    reason: Literal["weather", "pattern"],
    title: str,
    proposed_start: datetime,
    tz_str: str,
    evidence: dict[str, Any],
) -> str:
    """Use Nebius LLM client to produce a natural Turkish suggestion message."""
    try:
        tz = ZoneInfo(tz_str)
    except Exception:
        tz = ZoneInfo("UTC")

    local_start = proposed_start.astimezone(tz)
    day_name = local_start.strftime("%A")
    turkish_days = {
        "Monday": "Pazartesi",
        "Tuesday": "Salı",
        "Wednesday": "Çarşamba",
        "Thursday": "Perşembe",
        "Friday": "Cuma",
        "Saturday": "Cumartesi",
        "Sunday": "Pazar",
    }
    gun_str = turkish_days.get(day_name, day_name)
    saat_str = local_start.strftime("%H.%M")

    if reason == "weather":
        prompt_content = (
            f"Plan başlığı: '{title}'.\n"
            f"Durum: Yağmur bekleniyor.\n"
            f"Önerilen yeni zaman: {gun_str} {saat_str}.\n"
            "Kullanıcıya nazikçe hava durumu nedeniyle erteleme öneren 1 veya 2 cümlelik kısa Türkçe bir mesaj yaz. "
            "Örnek: 'Yağmur bekleniyor. Perşembe 19.00 uygun görünüyor. Ertelemek ister misin?'"
        )
    else:
        adherence = evidence.get("adherence_pct")
        prompt_content = (
            f"Plan başlığı: '{title}'.\n"
            f"Durum: Geçmiş plan tamamlama oranı %{adherence}.\n"
            f"Önerilen yeni zaman: {gun_str} {saat_str}.\n"
            "Kullanıcıya motivasyon sağlayan ve uygun yeni bir zaman öneren 1 veya 2 cümlelik kısa Türkçe bir mesaj yaz. "
            "Örnek: 'Bu saatlerdeki planlarda aksamalar olmuş. Perşembe 19.00 için planlamak ister misin?'"
        )

    messages = [
        {
            "role": "system",
            "content": "Sen GAP-AI asistanısın. Kullanıcıya sade, samimi ve kısa Türkçe erteleme veya zamanlama önerisi mesajı üret. Yalnızca mesaj metnini döndür.",
        },
        {"role": "user", "content": prompt_content},
    ]

    try:
        content = llm.complete(messages, temperature=0.2)
        message = content.strip().strip('"').strip("'")
        if message and len(message) <= 240 and "\n" not in message:
            return message
    except LLMError as exc:
        logger.warning("Nebius LLM call failed for suggestion message: %s", exc)

    # Deterministic fallback message if LLM is unavailable or empty
    if reason == "weather":
        return f"Yağmur bekleniyor. {gun_str} {saat_str} uygun görünüyor. Ertelemek ister misin?"
    return f"Geçmiş planlama alışkanlıklarına göre {gun_str} {saat_str} daha uygun görünüyor. Değiştirmek ister misin?"


@router.get("/plans/{plan_id}/suggestion", response_model=SuggestionResponse)
def get_suggestion_for_plan(
    plan_id: str,
    user: AuthenticatedUser = Depends(current_user),
    store: PlanStore = Depends(get_plan_store),
    llm: NebiusLLMClient = Depends(get_llm_client),
) -> dict[str, Any]:
    try:
        plan_id = str(UUID(plan_id))
    except ValueError:
        raise _plan_not_found() from None

    plan = store.get_plan(user_id=user.id, plan_id=plan_id)
    if plan is None:
        raise _plan_not_found()

    # A new reported outcome makes the saved recommendation stale. Return the
    # stored record unchanged until an outcome newer than it exists.
    existing = store.get_suggestion(user_id=user.id, plan_id=plan_id)
    existing_created = existing.get("created_at") if existing else None
    if existing is not None and existing_created is None:
        return {"suggestion": existing}
    if existing is not None:
        newer_outcome = False
        for historical in store.list_plans(user_id=user.id):
            outcome = historical.get("latest_outcome") or {}
            reported_at = outcome.get("reported_at")
            if reported_at and _parse_iso(reported_at) > _parse_iso(existing_created):
                newer_outcome = True
                break
        if not newer_outcome:
            return {"suggestion": {k: v for k, v in existing.items() if k != "created_at"}}

    now = datetime.now(timezone.utc)
    plan_start = _parse_iso(plan["planned_start"])
    plan_end = _parse_iso(plan["planned_end"])
    duration = plan_end - plan_start
    all_plans = store.list_plans(user_id=user.id)
    adherence_pct = _calculate_adherence_pct(all_plans, now)
    outcome_count = _reported_plan_count(all_plans, now)
    if outcome_count < 3:
        return {"suggestion": None}

    # Check weather using MVP Üsküdar–Bağlarbaşı coordinates
    is_rainy = False
    try:
        from app.services.weather import DEFAULT_LATITUDE, DEFAULT_LONGITUDE

        with WeatherService() as weather_service:
            forecast = weather_service.get_forecast(
                latitude=DEFAULT_LATITUDE,
                longitude=DEFAULT_LONGITUDE,
                target_time=plan_start,
                timezone_str=user.timezone,
            )
            if forecast and forecast.is_rainy:
                is_rainy = True
    except Exception as exc:
        logger.warning("Weather check exception: %s", exc)
        is_rainy = False

    reason: Literal["weather", "pattern"] | None = None
    evidence: dict[str, Any] = {}

    if is_rainy and outcome_count >= 3:
        reason = "weather"
        evidence["forecast"] = "rain"
        if adherence_pct is not None:
            evidence["adherence_pct"] = adherence_pct
    elif adherence_pct is not None and adherence_pct < 70.0 and outcome_count >= 3:
        # Pattern-based suggestion when adherence is low
        reason = "pattern"
        evidence["adherence_pct"] = adherence_pct
        evidence["outcome_count"] = outcome_count

    if reason is None:
        return {"suggestion": None}
    evidence["outcome_count"] = outcome_count

    # Deterministic time proposal: preserve the time-of-day and duration,
    # but ensure the proposed start is strictly in the future in the user's timezone.
    try:
        user_tz = ZoneInfo(user.timezone)
    except Exception:
        user_tz = ZoneInfo("UTC")

    local_plan_start = plan_start.astimezone(user_tz)
    local_now = now.astimezone(user_tz)

    # Propose starting tomorrow at the same local time, or advance day-by-day until strictly in the future
    candidate_start = local_plan_start + timedelta(days=1)
    if candidate_start <= local_now:
        # If plan is older, align to tomorrow relative to now, keeping the plan's local time-of-day
        tomorrow = local_now.date() + timedelta(days=1)
        candidate_start = datetime.combine(
            tomorrow,
            local_plan_start.time(),
            tzinfo=user_tz,
        )

    proposed_start = candidate_start
    proposed_end = proposed_start + duration

    # Generate message with Nebius LLM
    message = _generate_suggestion_message(
        llm,
        reason=reason,
        title=plan.get("title") or "Plan",
        proposed_start=proposed_start,
        tz_str=user.timezone,
        evidence=evidence,
    )

    suggestion_payload = {
        "plan_id": plan_id,
        "reason": reason,
        "message": message,
        "proposed_start": proposed_start.isoformat(),
        "proposed_end": proposed_end.isoformat(),
        "evidence": evidence,
    }

    if existing is not None:
        refresh = getattr(store, "refresh_suggestion", None)
        saved = (
            refresh(user.id, plan_id, suggestion_payload)
            if refresh
            else store.save_suggestion(user.id, plan_id, suggestion_payload)
        )
    else:
        saved = store.save_suggestion(user.id, plan_id, suggestion_payload)
    saved = {k: v for k, v in saved.items() if k != "created_at"}
    return {"suggestion": saved}
