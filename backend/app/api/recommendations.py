from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.api.errors import APIError
from app.api.plans import current_user
from app.db.plans import AuthenticatedUser, PlanStore, get_plan_store

router = APIRouter()


class FeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    recommendation_id: str = Field(min_length=1, max_length=80)
    action: Literal["accepted", "dismissed", "modified"]
    rating: Literal["useful", "not_useful"] | None = None
    payload: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_feedback(self) -> "FeedbackRequest":
        if self.action == "dismissed" and self.rating is not None:
            raise ValueError("Dismissed feedback cannot include a rating.")
        if self.action == "modified" and self.payload.get("duration_minutes") is not None:
            value = self.payload["duration_minutes"]
            if not isinstance(value, int) or not 5 <= value <= 1440:
                raise ValueError("duration_minutes must be between 5 and 1440.")
        return self


@router.post("/recommendations/feedback", status_code=201)
def create_feedback(payload: FeedbackRequest, user: AuthenticatedUser = Depends(current_user), store: PlanStore = Depends(get_plan_store)) -> dict[str, Any]:
    save = getattr(store, "save_recommendation_feedback", None)
    if save is None:
        raise APIError(503, "unavailable", "Recommendation feedback storage is unavailable.")
    row = save(user.id, payload.model_dump())
    row.pop("user_id", None)
    return row
