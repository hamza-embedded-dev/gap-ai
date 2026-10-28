from __future__ import annotations

import logging
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, ConfigDict

from app.ai.speech_sanitizer import sanitize_for_speech
from app.ai.tts import GroqTTSClient, TTSError, get_tts_client
from app.api.errors import APIError
from app.api.plans import PlanResponse, current_user
from app.db.plans import AuthenticatedUser, PlanStore, get_plan_store
from app.schemas.conversation import ConversationState
from app.services.conversation import get_conversation_engine

logger = logging.getLogger(__name__)

router = APIRouter()


class ProposalResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    user_id: str
    title: str
    category: str
    planned_start: str
    planned_end: str
    duration_minutes: int | None = None
    recurrence_rule: str | None = None
    status: str
    created_at: str


class AcceptProposalResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: str
    plan: PlanResponse
    reply_text: str


class RejectProposalResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: str
    proposal_id: str
    reply_text: str


@router.get(
    "/plans/proposals/pending",
    response_model=ProposalResponse | None,
    status_code=status.HTTP_200_OK,
)
def get_pending_proposal(
    user: AuthenticatedUser = Depends(current_user),
    store: PlanStore = Depends(get_plan_store),
) -> ProposalResponse | None:
    """Returns the user's latest pending plan proposal awaiting approval, or null."""
    proposal = store.get_latest_pending_proposal(user_id=user.id)
    if not proposal:
        return None
    return ProposalResponse.model_validate(proposal)


@router.post(
    "/plans/proposals/accept",
    response_model=AcceptProposalResponse,
    status_code=status.HTTP_200_OK,
)
def accept_proposal_endpoint(
    request: Request,
    proposal_id: str | None = None,
    user: AuthenticatedUser = Depends(current_user),
    store: PlanStore = Depends(get_plan_store),
    tts_client: GroqTTSClient = Depends(get_tts_client),
) -> Response | AcceptProposalResponse:
    """Triggered by hardware action button (or web UI) to confirm a drafted plan."""
    try:
        proposal, plan = store.accept_plan_proposal(user_id=user.id, proposal_id=proposal_id)
    except ValueError as exc:
        raise APIError(
            404,
            "not_found",
            "No pending plan proposal found to accept.",
        ) from exc

    conv_engine = get_conversation_engine()
    active_sess = conv_engine.get_active_session_for_user(user.id)
    if active_sess:
        active_sess.state = ConversationState.COMPLETED
        active_sess.created_plan_id = str(plan.get("id"))
        active_sess.created_plan = plan
        conv_engine.clear_active_session_for_user(user.id)

    title = plan.get("title", "Plan")
    time_part = plan.get("planned_start", "")[11:16]
    date_part = plan.get("planned_start", "")[:10]
    spoken_reply = sanitize_for_speech(
        f"Great, your plan for {title} on {date_part} at {time_part} has been confirmed."
    )

    accept_header = request.headers.get("accept", "")
    if "audio/wav" in accept_header:
        try:
            wav_bytes = tts_client.synthesize(spoken_reply)
            headers = {
                "Content-Type": "audio/wav",
                "X-Plan-Id": str(plan.get("id")),
                "X-Reply-Text": quote(spoken_reply, safe=""),
                "X-Status": "accepted",
                "X-Intent": "plan_accepted",
            }
            return Response(content=wav_bytes, media_type="audio/wav", headers=headers)
        except Exception as exc:
            logger.warning("TTS generation failed on proposal accept: %s", exc)

    return AcceptProposalResponse(
        status="accepted",
        plan=PlanResponse.model_validate(plan),
        reply_text=spoken_reply,
    )


@router.post(
    "/plans/proposals/reject",
    response_model=RejectProposalResponse,
    status_code=status.HTTP_200_OK,
)
def reject_proposal_endpoint(
    request: Request,
    proposal_id: str | None = None,
    user: AuthenticatedUser = Depends(current_user),
    store: PlanStore = Depends(get_plan_store),
    tts_client: GroqTTSClient = Depends(get_tts_client),
) -> Response | RejectProposalResponse:
    """Triggered by hardware cancel/reject button (or web UI) to cancel a drafted plan."""
    try:
        proposal = store.reject_plan_proposal(user_id=user.id, proposal_id=proposal_id)
    except ValueError as exc:
        raise APIError(
            404,
            "not_found",
            "No pending plan proposal found to reject.",
        ) from exc

    conv_engine = get_conversation_engine()
    active_sess = conv_engine.get_active_session_for_user(user.id)
    if active_sess:
        active_sess.state = ConversationState.CANCELLED
        conv_engine.clear_active_session_for_user(user.id)

    title = proposal.get("title", "Plan")
    spoken_reply = sanitize_for_speech(f"Okay, I have cancelled the draft for {title}.")

    accept_header = request.headers.get("accept", "")
    if "audio/wav" in accept_header:
        try:
            wav_bytes = tts_client.synthesize(spoken_reply)
            headers = {
                "Content-Type": "audio/wav",
                "X-Proposal-Id": str(proposal.get("id")),
                "X-Reply-Text": quote(spoken_reply, safe=""),
                "X-Status": "rejected",
                "X-Intent": "plan_rejected",
            }
            return Response(content=wav_bytes, media_type="audio/wav", headers=headers)
        except Exception as exc:
            logger.warning("TTS generation failed on proposal reject: %s", exc)

    return RejectProposalResponse(
        status="rejected",
        proposal_id=str(proposal.get("id")),
        reply_text=spoken_reply,
    )
