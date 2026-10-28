from __future__ import annotations

from enum import Enum
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field

from app.schemas.parsed_plan import ParsedPlan

class ProposalSnapshot(BaseModel):
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


class ConversationState(str, Enum):
    COLLECTING_DETAILS = "collecting_details"
    AWAITING_CLARIFICATION = "awaiting_clarification"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    UNSUPPORTED = "unsupported"


class PendingPlan(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str | None = None
    category: str | None = None
    date: str | None = None  # YYYY-MM-DD
    time: str | None = None  # HH:MM (24-hour format)
    duration_minutes: int | None = 60
    recurrence: str | None = None
    needs_weather_check: bool = False
    clarification_question: str | None = None
    time_is_ambiguous: bool = False


class ConversationRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    text: str | None = None
    message: str | None = None
    conversation_id: str | None = None
    current_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    timezone: str | None = None
    language: Literal["en"] | None = "en"

    @property
    def clean_text(self) -> str:
        return (self.text or self.message or "").strip()


class ConversationResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    conversation_id: str
    state: ConversationState
    reply_text: str
    prompt_type: str  # "clarification" | "confirmation" | "success" | "cancellation" | "unsupported" | "info"
    pending_plan: PendingPlan | None = None
    parsed_plan: ParsedPlan | None = None
    proposal: ProposalSnapshot | None = None
    plan: dict[str, Any] | None = None
    needs_button: bool = False


ConversationResponse.model_rebuild()

