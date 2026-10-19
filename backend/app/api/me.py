from __future__ import annotations

from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

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
