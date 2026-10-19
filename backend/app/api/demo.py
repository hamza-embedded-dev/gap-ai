from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from starlette.exceptions import HTTPException

from app.config import get_settings
from app.db.demo_seed import materialize_demo_profile
from app.db.plans import PlanStore, get_plan_store

router = APIRouter()


class DemoSessionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str
    expires_at: datetime
    is_demo: Literal[True] = True


@router.post("/demo/session", response_model=DemoSessionResponse, status_code=201)
def create_demo_session(
    store: PlanStore = Depends(get_plan_store),
) -> DemoSessionResponse:
    settings = get_settings()
    if settings.token_hash_pepper is None:
        raise HTTPException(
            status_code=500,
            detail="Token hash pepper is not configured.",
        )

    raw_token = secrets.token_urlsafe(32)
    pepper = settings.token_hash_pepper.get_secret_value()
    token_hash = hashlib.sha256((raw_token + pepper).encode("utf-8")).hexdigest()

    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(hours=24)

    user = store.create_demo_session(
        token_hash=token_hash,
        created_at=now,
        expires_at=expires_at,
    )
    try:
        plans, outcomes = materialize_demo_profile(
            user.id, profile_id="regular", session_started_at=now
        )
        plan_ids: set[str] = set()
        for plan in plans:
            created_plan = store.create_plan(plan)
            plan_ids.add(str(created_plan["id"]))
        for outcome in outcomes:
            plan_id = str(outcome["plan_id"])
            if plan_id not in plan_ids:
                raise RuntimeError("Demo seed outcome references an uncreated plan")
            store.create_outcome(
                user_id=user.id,
                plan_id=plan_id,
                outcome=outcome,
            )
    except Exception:
        try:
            store.delete_demo_session(user_id=user.id)
        except Exception:
            # Keep the seeding failure visible; deletion is best-effort cleanup.
            pass
        raise

    return DemoSessionResponse(
        token=raw_token,
        expires_at=expires_at,
        is_demo=True,
    )
