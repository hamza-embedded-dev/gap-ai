from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Header, status

from app.ai.llm import NebiusLLMClient, get_llm_client
from app.api.plans import current_user
from app.db.plans import AuthenticatedUser, PlanStore, get_plan_store
from app.schemas.conversation import (
    ConversationRequest,
    ConversationResponse,
    ConversationState,
    PendingPlan,
    ProposalSnapshot,
)
from app.services.conversation import ConversationEngine, get_conversation_engine

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/conversation", tags=["conversation"])


@router.post("", response_model=ConversationResponse, status_code=status.HTTP_200_OK)
def conversation_endpoint(
    payload: ConversationRequest,
    user: AuthenticatedUser = Depends(current_user),
    store: PlanStore = Depends(get_plan_store),
    llm_client: NebiusLLMClient = Depends(get_llm_client),
    engine: ConversationEngine = Depends(get_conversation_engine),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> ConversationResponse:
    """Shared conversational scheduling endpoint serving both Web and external clients."""
    result = engine.process_message(
        user=user,
        text=payload.clean_text,
        conversation_id=payload.conversation_id,
        current_date=payload.current_date,
        timezone_name=payload.timezone,
        store=store,
        llm_client=llm_client,
        idempotency_key=idempotency_key,
        source="web",
    )

    prop = ProposalSnapshot.model_validate(result.proposal) if result.proposal else None

    return ConversationResponse(
        conversation_id=result.conversation_id,
        state=result.state,
        reply_text=result.reply_text,
        prompt_type=result.prompt_type,
        pending_plan=PendingPlan.model_validate(result.pending_plan) if result.pending_plan else None,
        proposal=prop,
        plan=result.plan,
        needs_button=result.needs_button,
    )


@router.get("/active", response_model=ConversationResponse | None, status_code=status.HTTP_200_OK)
def get_active_conversation_endpoint(
    user: AuthenticatedUser = Depends(current_user),
    engine: ConversationEngine = Depends(get_conversation_engine),
) -> ConversationResponse | None:
    """Returns the user's active pending conversation if any."""
    session = engine.get_active_session_for_user(user.id)
    if not session:
        return None

    return ConversationResponse(
        conversation_id=session.id,
        state=session.state,
        reply_text=session.last_assistant_message or "",
        prompt_type="confirmation" if session.state == ConversationState.AWAITING_CONFIRMATION else "clarification",
        pending_plan=session.pending_plan,
        proposal=None,
        plan=None,
        needs_button=(session.state == ConversationState.AWAITING_CONFIRMATION),
    )


@router.post("/cancel", response_model=ConversationResponse, status_code=status.HTTP_200_OK)
def cancel_conversation_endpoint(
    user: AuthenticatedUser = Depends(current_user),
    store: PlanStore = Depends(get_plan_store),
    engine: ConversationEngine = Depends(get_conversation_engine),
) -> ConversationResponse:
    """Explicitly cancels the user's active pending conversation."""
    result = engine.process_message(
        user=user,
        text="cancel",
        store=store,
        source="web",
    )
    return ConversationResponse(
        conversation_id=result.conversation_id,
        state=result.state,
        reply_text=result.reply_text,
        prompt_type=result.prompt_type,
        pending_plan=PendingPlan.model_validate(result.pending_plan) if result.pending_plan else None,
        proposal=None,
        plan=None,
        needs_button=False,
    )


@router.post("/confirm", response_model=ConversationResponse, status_code=status.HTTP_200_OK)
def confirm_conversation_endpoint(
    user: AuthenticatedUser = Depends(current_user),
    store: PlanStore = Depends(get_plan_store),
    engine: ConversationEngine = Depends(get_conversation_engine),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> ConversationResponse:
    """Explicitly confirms the user's active pending conversation and persists the plan."""
    result = engine.process_message(
        user=user,
        text="confirm",
        store=store,
        idempotency_key=idempotency_key,
        source="web",
    )
    return ConversationResponse(
        conversation_id=result.conversation_id,
        state=result.state,
        reply_text=result.reply_text,
        prompt_type=result.prompt_type,
        pending_plan=PendingPlan.model_validate(result.pending_plan) if result.pending_plan else None,
        proposal=None,
        plan=result.plan,
        needs_button=False,
    )
