from __future__ import annotations

from datetime import date
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.api.errors import APIError
from app.api.plans import current_user
from app.db.plans import AuthenticatedUser, PlanStore, get_plan_store

router = APIRouter()


class ProfileResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    display_name: str | None
    timezone: str
    is_demo: bool


class ProfilePatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = None
    timezone: str | None = None


class ProfileGoal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=160)
    deadline: date | None
    kind: Literal["goal", "exam", "deadline"]

    @field_validator("title")
    @classmethod
    def trim_goal_title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Goal title cannot be blank")
        return value


class PersonalizationPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    preferred_name: str | None = Field(default=None, max_length=80)
    age_range: Literal["under_18", "18_24", "25_34", "35_44", "45_plus", "prefer_not_to_say"] | None = None
    life_context: Literal["student", "working", "other"] | None = None
    field_of_study: str | None = Field(default=None, max_length=120)
    study_year: str | None = Field(default=None, max_length=40)
    deadlines_goals: list[ProfileGoal] = Field(default_factory=list, max_length=30)
    work_schedule: str | None = Field(default=None, max_length=500)
    typical_availability: list[str] = Field(default_factory=list, max_length=30)
    interests: list[str] = Field(default_factory=list, max_length=30)
    skills_to_develop: list[str] = Field(default_factory=list, max_length=30)
    planning_preferences: list[str] = Field(default_factory=list, max_length=30)
    recommendation_frequency: Literal["daily", "weekly", "on_demand", "off"] | None = None
    onboarding_skipped: list[str] = Field(default_factory=list, max_length=30)
    onboarding_completed: list[str] = Field(default_factory=list, max_length=30)

    @field_validator("preferred_name", "field_of_study", "study_year", "work_schedule")
    @classmethod
    def trim_text(cls, value):
        return value.strip() if value is not None else value

    @field_validator("typical_availability", "interests", "skills_to_develop", "planning_preferences", "onboarding_skipped", "onboarding_completed")
    @classmethod
    def valid_string_items(cls, values):
        if any(not value.strip() or len(value) > 120 for value in values or []):
            raise ValueError("Profile list values must contain 1 to 120 characters")
        if len(set(values or [])) != len(values or []):
            raise ValueError("Profile list values must be unique")
        return values

    @field_validator("onboarding_skipped", "onboarding_completed")
    @classmethod
    def valid_progress_fields(cls, values):
        allowed = {"preferred_name", "age_range", "life_context", "field_of_study", "study_year", "deadlines_goals", "work_schedule", "typical_availability", "interests", "skills_to_develop", "planning_preferences", "recommendation_frequency"}
        if any(value not in allowed for value in values or []):
            raise ValueError("Onboarding progress contains an unknown profile field")
        return values


@router.get("/me/profile")
def get_personalization(user: AuthenticatedUser = Depends(current_user), store: PlanStore = Depends(get_plan_store)):
    return _normalized_personalization(store.get_personalization(user_id=user.id), user.id)


@router.patch("/me/profile")
def patch_personalization(payload: PersonalizationPatch, user: AuthenticatedUser = Depends(current_user), store: PlanStore = Depends(get_plan_store)):
    changes = payload.model_dump(exclude_unset=True, mode="json")
    cleared_fields = {key for key, value in changes.items() if value is None}
    if cleared_fields:
        current = store.get_personalization(user_id=user.id)
        changes["onboarding_skipped"] = [key for key in current.get("onboarding_skipped", []) if key not in cleared_fields]
        changes["onboarding_completed"] = [key for key in current.get("onboarding_completed", []) if key not in cleared_fields]
    profile = store.update_personalization(user_id=user.id, changes=changes)
    return _normalized_personalization(profile, user.id)


@router.delete("/me/profile/fields/{field_name}")
def delete_profile_field(field_name: str, user: AuthenticatedUser = Depends(current_user), store: PlanStore = Depends(get_plan_store)):
    if field_name not in PersonalizationPatch.model_fields or field_name in {"onboarding_skipped", "onboarding_completed"}:
        raise APIError(422, "validation_error", "Unknown profile field.")
    current = store.get_personalization(user_id=user.id)
    skipped = list(current.get("onboarding_skipped") or [])
    completed = list(current.get("onboarding_completed") or [])
    if field_name in skipped: skipped.remove(field_name)
    if field_name in completed: completed.remove(field_name)
    empty_value: Any = [] if field_name in {"deadlines_goals", "typical_availability", "interests", "skills_to_develop", "planning_preferences"} else None
    return _normalized_personalization(store.update_personalization(user_id=user.id, changes={field_name: empty_value, "onboarding_skipped": skipped, "onboarding_completed": completed}), user.id)


@router.delete("/me/profile")
def reset_personalization(user: AuthenticatedUser = Depends(current_user), store: PlanStore = Depends(get_plan_store)):
    store.reset_personalization(user_id=user.id)
    return {"deleted": True}


def _normalized_personalization(profile: dict[str, Any], user_id: str) -> dict[str, Any]:
    defaults: dict[str, Any] = {
        "preferred_name": None, "age_range": None, "life_context": None,
        "field_of_study": None, "study_year": None, "deadlines_goals": [],
        "work_schedule": None, "typical_availability": [], "interests": [],
        "skills_to_develop": [], "planning_preferences": [],
        "recommendation_frequency": None, "onboarding_skipped": [], "onboarding_completed": [],
    }
    return {"user_id": user_id, **defaults, **{k: v for k, v in profile.items() if k in defaults}}


def _profile_from_user(user: AuthenticatedUser) -> dict[str, Any]:
    return {
        "id": user.id,
        "display_name": user.display_name,
        "timezone": user.timezone,
        "is_demo": user.is_demo,
    }


@router.get("/me", response_model=ProfileResponse)
def get_me(user: AuthenticatedUser = Depends(current_user)) -> dict[str, Any]:
    return _profile_from_user(user)


@router.patch("/me", response_model=ProfileResponse)
def patch_me(
    payload: ProfilePatchRequest,
    user: AuthenticatedUser = Depends(current_user),
    store: PlanStore = Depends(get_plan_store),
) -> dict[str, Any]:
    changes = payload.model_dump(exclude_unset=True)
    if "timezone" in changes:
        timezone_name = changes["timezone"]
        if not isinstance(timezone_name, str):
            raise APIError(422, "validation_error", "Timezone must be an IANA timezone name.")
        try:
            ZoneInfo(timezone_name)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise APIError(
                422, "validation_error", "Timezone must be an IANA timezone name."
            ) from exc

    if not changes:
        return _profile_from_user(user)

    update = getattr(store, "update_profile", None)
    if update is None:
        raise NotImplementedError("PlanStore implementation does not support profile updates yet.")
    profile = update(user_id=user.id, changes=changes)
    if profile is None:
        raise APIError(404, "not_found", "User not found.")
    return profile
