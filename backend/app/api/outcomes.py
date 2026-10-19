from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import AwareDatetime, BaseModel, ConfigDict, model_validator

from app.api.errors import APIError
from app.api.plans import current_user
from app.db.plans import AuthenticatedUser, PlanStore, get_plan_store

router = APIRouter()


class OutcomeCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["done", "postponed", "skipped"]
    actual_start: AwareDatetime | None = None
    # Devices may report "postponed" without a target time; insights count
    # it as a postponement with an unknown target.
    postponed_to: AwareDatetime | None = None
    note: str | None = None
    reported_via: Literal["web", "device", "auto"]

    @model_validator(mode="after")
    def postponed_to_requires_postponed_status(self) -> "OutcomeCreateRequest":
        if self.postponed_to is not None and self.status != "postponed":
            raise ValueError("postponed_to is only allowed when status is postponed")
        return self


class OutcomeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    plan_id: str
    status: Literal["done", "postponed", "skipped"]
    actual_start: datetime | None
    postponed_to: datetime | None
    note: str | None
    reported_via: Literal["web", "device", "auto"]
    reported_at: datetime


def _plan_not_found() -> APIError:
    # K-1: a plan owned by someone else looks exactly like a missing plan.
    return APIError(404, "not_found", "Plan not found.")


@router.post("/plans/{plan_id}/outcome", response_model=OutcomeResponse, status_code=201)
def create_outcome(
    plan_id: str,
    request: OutcomeCreateRequest,
    user: AuthenticatedUser = Depends(current_user),
    store: PlanStore = Depends(get_plan_store),
) -> dict[str, Any]:
    try:
        plan_id = str(UUID(plan_id))
    except ValueError:
        raise _plan_not_found() from None

    get_plan = getattr(store, "get_plan", None)
    store_outcome = getattr(store, "create_outcome", None)
    if get_plan is None or store_outcome is None:
        raise NotImplementedError("PlanStore implementation does not support outcomes yet.")

    if get_plan(user_id=user.id, plan_id=plan_id) is None:
        raise _plan_not_found()

    # Outcomes are append-only events: every report inserts a new row.
    row = store_outcome(
        user_id=user.id,
        plan_id=plan_id,
        outcome=request.model_dump(mode="json"),
    )
    # Return only contract fields; the stored row also carries user_id.
    return {field: row[field] for field in OutcomeResponse.model_fields}
