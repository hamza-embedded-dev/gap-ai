from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from starlette.exceptions import HTTPException

from app.config import get_settings
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

    store.create_demo_session(
        token_hash=token_hash,
        created_at=now,
        expires_at=expires_at,
    )

    return DemoSessionResponse(
        token=raw_token,
        expires_at=expires_at,
        is_demo=True,
    )
