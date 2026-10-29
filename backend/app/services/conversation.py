from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
import hashlib
import json
import logging
import re
from typing import Any
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException


from app.ai.llm import (
    LLMConfigurationError,
    LLMParseError,
    LLMResponseError,
    LLMUnavailableError,
    NebiusLLMClient,
    get_llm_client,
)
from app.ai.speech_sanitizer import sanitize_for_speech
from app.api.errors import APIError
from app.api.parse import parse_text
from app.analytics.insights import calculate_recommendations
from app.db.plans import AuthenticatedUser, PlanStore, get_plan_store
from app.recommendations import apply_policy, build_contextual_recommendations
from app.schemas.conversation import ConversationState, PendingPlan
from app.schemas.parsed_plan import ParsedPlan

logger = logging.getLogger(__name__)

SCHEDULING_TIMEZONE = "Europe/Istanbul"

# Word to number mappings for hours and durations
NUMBER_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4,
    "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12,
}

DURATION_WORDS: dict[str, int] = {
    "five": 5,
    "ten": 10,
    "fifteen": 15,
    "twenty": 20,
    "twenty five": 25,
    "twenty-five": 25,
    "thirty": 30,
    "thirty five": 35,
    "thirty-five": 35,
    "forty": 40,
    "forty five": 45,
    "forty-five": 45,
    "fifty": 50,
    "sixty": 60,
    "seventy five": 75,
    "seventy-five": 75,
    "ninety": 90,
    "one hundred twenty": 120,
    "one hour": 60,
    "an hour": 60,
    "two hours": 120,
    "three hours": 180,
    "half an hour": 30,
    "half hour": 30,
}

WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}

CONFIRMATION_PATTERNS = {
    "yes", "confirm", "yes please", "sure", "sounds good", "create it", "save it",
    "go ahead", "yep", "yeah", "ok", "okay", "1", "do it", "please do",
    "looks good", "correct", "perfect", "accept", "proceed", "yes confirm",
    "confirm it", "right", "right.", "thats right", "that is right", "all right",
    "alright", "do that", "okay do it", "onayla", "evet", "tamam", "bunu yapalım", "kabul",
}

CANCELLATION_PATTERNS = {
    "cancel", "cancel that", "no", "no thanks", "don't create it", "don't create",
    "discard", "never mind", "stop", "abort", "2", "reject", "don't save",
    "nevermind", "cancel it", "no cancel", "iptal", "vazgeç", "hayır iptal", "istemiyorum",
}


@dataclass
class ConversationSession:
    id: str
    user_id: str
    state: ConversationState = ConversationState.COLLECTING_DETAILS
    pending_plan: PendingPlan = field(default_factory=PendingPlan)
    history: list[dict[str, str]] = field(default_factory=list)
    proposal_id: str | None = None
    created_plan_id: str | None = None
    created_plan: dict[str, Any] | None = None
    idempotency_key: str | None = None
    last_assistant_message: str | None = None
    last_clarification_field: str | None = None
    ambiguous_hour: int | None = None
    mode: str = "plan"
    current_recommendation: dict[str, Any] | None = None
    recommendations_pool: list[dict[str, Any]] = field(default_factory=list)
    shown_recommendation_ids: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class ConversationTurnResult:
    conversation_id: str
    state: ConversationState
    reply_text: str
    prompt_type: str  # "clarification" | "confirmation" | "success" | "cancellation" | "unsupported" | "info"
    pending_plan: dict[str, Any] | None = None
    parsed_plan: ParsedPlan | None = None
    proposal: dict[str, Any] | None = None
    plan: dict[str, Any] | None = None
    recommendation: dict[str, Any] | None = None
    needs_button: bool = False


def is_pending_plan_query(text: str) -> bool:
    clean = re.sub(r"[^\w\s]", "", text.lower()).strip()
    return bool(
        re.search(r"\b(do i have|any|what is|check|show|list)\s+(?:a\s+)?pending\s+plans?\b", clean)
        or re.search(r"\b(bekleyen|aktif)\s+(?:bir\s+)?plan(?:im|ım)?\s*(?:var\s+mi|nedir)?\b", clean)
        or clean in ("pending plans", "pending plan", "do i have pending plans", "do i have a pending plan")
    )


def _parse_hour_int(val: str) -> int | None:
    val_clean = val.strip().lower()
    if val_clean.isdigit():
        h = int(val_clean)
        return h if 0 <= h <= 23 else None
    return NUMBER_WORDS.get(val_clean)


def resolve_relative_date(text: str, current_date: date) -> date | None:
    """Resolves relative date expressions in text relative to current_date."""
    lower = text.lower()

    # Check for weekday mentions first (e.g. "Friday", "not tomorrow, Friday", "this Friday")
    for day_name, day_idx in WEEKDAYS.items():
        if re.search(rf"\b{day_name}\b", lower):
            cur_weekday = current_date.weekday()
            days_ahead = (day_idx - cur_weekday) % 7
            if days_ahead == 0:
                days_ahead = 7
            return current_date + timedelta(days=days_ahead)

    if "day after tomorrow" in lower and not re.search(r"\bnot\s+(?:the\s+)?day\s+after\s+tomorrow\b", lower):
        return current_date + timedelta(days=2)
    if "tomorrow" in lower and not re.search(r"\bnot\s+tomorrow\b", lower):
        return current_date + timedelta(days=1)
    if "today" in lower and not re.search(r"\bnot\s+today\b", lower):
        return current_date

    # Check for ISO YYYY-MM-DD
    iso_match = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", lower)
    if iso_match:
        try:
            return date.fromisoformat(iso_match.group(1))
        except ValueError:
            pass

    return None


def extract_duration_minutes(text: str) -> int | None:
    """Extracts duration in minutes from natural English."""
    lower = text.lower()

    # "two hours", "2 hours", "for two hours", "make it two hours"
    m_hour = re.search(r"\b(?:for\s+|make it\s+)?(\d+|one|two|three|four|five|six|seven|eight)\s+hours?\b", lower)
    if m_hour:
        h = _parse_hour_int(m_hour.group(1))
        if h is not None:
            return h * 60

    # "half an hour" / "half hour"
    if "half an hour" in lower or "half hour" in lower:
        return 30

    # "an hour" / "one hour"
    if re.search(r"\b(?:for\s+|make it\s+)?an?\s+hour\b", lower):
        return 60

    # "30 minutes", "45 minutes", "90 minutes"
    m_min = re.search(r"\b(?:for\s+|make it\s+)?(\d+)\s+minutes?\b", lower)
    if m_min:
        return int(m_min.group(1))

    return None


def extract_contextual_duration(text: str) -> int | None:
    """Extracts duration in minutes contextually when duration was specifically requested."""
    # First check standard explicit duration expressions like "30 minutes", "for 2 hours", etc.
    d = extract_duration_minutes(text)
    if d is not None:
        return d

    clean = re.sub(r"[^\w\s-]", "", text.lower()).strip()
    if clean.isdigit():
        val = int(clean)
        if 5 <= val <= 720:
            return val

    if clean in DURATION_WORDS:
        return DURATION_WORDS[clean]

    # Handle "about thirty", "around 45", "just 30"
    m_word = re.search(r"\b(?:about|around|just|make it)?\s*([a-z-]+)\b", clean)
    if m_word and m_word.group(1) in DURATION_WORDS:
        return DURATION_WORDS[m_word.group(1)]

    m_digit = re.search(r"\b(?:about|around|just|make it)?\s*(\d{1,3})\b", clean)
    if m_digit:
        val = int(m_digit.group(1))
        if 5 <= val <= 720:
            return val

    return None


def is_awaiting_duration_clarification(session: ConversationSession) -> bool:
    if session.state != ConversationState.AWAITING_CLARIFICATION:
        return False
    if session.last_clarification_field == "duration":
        return True
    last_q = (session.pending_plan.clarification_question or session.last_assistant_message or "").lower()
    return any(k in last_q for k in ["how long", "duration", "how many minutes", "how many hours", "length"])


def extract_time_and_ambiguity(text: str) -> tuple[str | None, bool, int | None]:
    """Analyzes text for time expressions.

    Returns:
        (resolved_time_24h, is_ambiguous, ambiguous_hour)
        - If resolved_time_24h is set, returns HH:MM in 24h format.
        - If is_ambiguous is True, returns True and the 12-hour digit (e.g. 5).
    """
    lower = text.lower()
    # Normalize "a.m." -> "am", "p.m." -> "pm", "a.m" -> "am", "p.m" -> "pm"
    lower = re.sub(r"\b([ap])\.m\.?", r"\1m", lower)

    # 1. Check for explicit AM/PM with digits or words:
    # "5 PM", "5:00 PM", "5:30 pm", "5pm", "5 am", "5am", "2 a.m.", "2 p.m."
    m_ampm = re.search(r"\b(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", lower)
    if m_ampm:
        hour = int(m_ampm.group(1))
        minute = int(m_ampm.group(2) or 0)
        period = m_ampm.group(3)
        if period == "pm" and hour != 12:
            hour += 12
        elif period == "am" and hour == 12:
            hour = 0
        return f"{hour:02d}:{minute:02d}", False, None

    # Words like "five pm", "five am", "two am", "two pm", "two a.m."
    m_word_ampm = re.search(
        r"\b(?:at\s+)?(one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\s*(am|pm)\b",
        lower,
    )
    if m_word_ampm:
        h_word = m_word_ampm.group(1)
        period = m_word_ampm.group(2)
        hour = NUMBER_WORDS.get(h_word, 0)
        if period == "pm" and hour != 12:
            hour += 12
        elif period == "am" and hour == 12:
            hour = 0
        return f"{hour:02d}:00", False, None

    # Check for standalone "pm" or "am" (as an answer to "Do you mean 5 AM or 5 PM?")
    if re.fullmatch(r"^\s*pm\s*$", lower):
        return None, False, None  # Caller resolves using session.ambiguous_hour
    if re.fullmatch(r"^\s*am\s*$", lower):
        return None, False, None

    # 2. Check for 24-hour military format (e.g. "17:00", "08:30", "14:00")
    m_24h = re.search(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", lower)
    if m_24h:
        hour = int(m_24h.group(1))
        minute = int(m_24h.group(2))
        return f"{hour:02d}:{minute:02d}", False, None

    # 3. Check for contextual morning / evening modifiers:
    # "at 5 in the evening", "5 in the morning", "at 8 tonight"
    m_ctx = re.search(
        r"\b(?:at\s+)?(\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)"
        r"(?:\s+o'?clock)?\s+(?:in\s+the\s+)?(morning|evening|afternoon|night)\b",
        lower,
    )
    if m_ctx:
        h = _parse_hour_int(m_ctx.group(1))
        if h is not None:
            mod = m_ctx.group(2)
            if mod in ("evening", "afternoon", "night") and h < 12:
                h += 12
            elif mod == "morning" and h == 12:
                h = 0
            return f"{h:02d}:00", False, None

    # 4. Check for bare hour with "at" or "o'clock" or bare hour answer:
    # "at five", "at 5", "5 o'clock", or direct answer "at 5.", "five"
    # Negative lookahead prevents matching duration quantities such as "two hours"
    m_bare = re.search(
        r"\b(?:at\s+)?(\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)(?!\s*(?:hours?|hrs?|minutes?|mins?))(?:\s+o'?clock)?\b",
        lower,
    )
    if m_bare:
        h = _parse_hour_int(m_bare.group(1))
        if h is not None and 1 <= h <= 12:
            # 1 to 11 are ambiguous between AM and PM in schedule planning
            return None, True, h

    return None, False, None


def format_confirmation_summary(pending: PendingPlan, current_date: date) -> str:
    """Formats an interpreted pending plan into a natural English confirmation question.

    Example:
    "Create a plan to study tomorrow, Thursday, October 29, at 5:00 PM for two hours?"
    """
    task = (pending.title or "activity").strip()

    # Format date
    if pending.date:
        try:
            plan_date = date.fromisoformat(pending.date)
            delta_days = (plan_date - current_date).days
            day_name = plan_date.strftime("%A")
            month_name = plan_date.strftime("%B")
            day_num = plan_date.day

            if delta_days == 1:
                date_str = f"tomorrow, {day_name}, {month_name} {day_num}"
            elif delta_days == 0:
                date_str = f"today, {day_name}, {month_name} {day_num}"
            else:
                date_str = f"on {day_name}, {month_name} {day_num}"
        except ValueError:
            date_str = f"on {pending.date}"
    else:
        date_str = "soon"

    # Format time (12-hour format with AM/PM)
    if pending.time:
        try:
            plan_time = time.fromisoformat(pending.time)
            hour_12 = plan_time.hour % 12
            if hour_12 == 0:
                hour_12 = 12
            period = "PM" if plan_time.hour >= 12 else "AM"
            time_str = f"at {hour_12}:{plan_time.minute:02d} {period}"
        except ValueError:
            time_str = f"at {pending.time}"
    else:
        time_str = ""

    # Format duration
    duration = pending.duration_minutes or 60
    if duration == 60:
        duration_str = "for one hour"
    elif duration == 120:
        duration_str = "for two hours"
    elif duration % 60 == 0:
        duration_str = f"for {duration // 60} hours"
    else:
        duration_str = f"for {duration} minutes"

    parts = [f"Create a plan to {task.lower()}", date_str, time_str, duration_str]
    clean_parts = [p for p in parts if p]
    return " ".join(clean_parts).replace("  ", " ") + "?"


class ConversationEngine:
    """Shared backend conversation orchestration engine.

    Serves both Web application and ESP32 voice interface with identical business rules.
    """

    SESSION_TIMEOUT_SECONDS: int = 600

    def __init__(self) -> None:
        self._sessions: dict[str, ConversationSession] = {}
        self._user_active_sessions: dict[str, str] = {}  # user_id -> conversation_id

    def get_session(self, conversation_id: str) -> ConversationSession | None:
        sess = self._sessions.get(conversation_id)
        if not sess:
            return None
        now = datetime.now(timezone.utc)
        if (now - sess.updated_at).total_seconds() > self.SESSION_TIMEOUT_SECONDS:
            self._sessions.pop(conversation_id, None)
            if self._user_active_sessions.get(sess.user_id) == conversation_id:
                self._user_active_sessions.pop(sess.user_id, None)
            return None
        return sess

    def get_active_session_for_user(self, user_id: str) -> ConversationSession | None:
        cid = self._user_active_sessions.get(user_id)
        if not cid:
            return None
        sess = self.get_session(cid)
        if sess and sess.state in (
            ConversationState.COLLECTING_DETAILS,
            ConversationState.AWAITING_CLARIFICATION,
            ConversationState.AWAITING_CONFIRMATION,
        ):
            return sess
        return None

    def clear_active_session_for_user(self, user_id: str) -> None:
        self._user_active_sessions.pop(user_id, None)

    def process_message(
        self,
        *,
        user: AuthenticatedUser,
        text: str,
        mode: str = "plan",
        conversation_id: str | None = None,
        current_date: str | date | None = None,
        timezone_name: str | None = None,
        store: PlanStore,
        llm_client: NebiusLLMClient | None = None,
        parsed_plan: ParsedPlan | None = None,
        idempotency_key: str | None = None,
        source: str = "web",
    ) -> ConversationTurnResult:
        """Processes an incoming conversation message turn."""
        clean_text = text.strip()
        if not clean_text:
            raise APIError(422, "validation_error", "Message text cannot be empty.")

        # 1. Resolve Timezone and Calendar Date
        tz = timezone_name or user.timezone or SCHEDULING_TIMEZONE
        try:
            zone = ZoneInfo(tz)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise APIError(422, "validation_error", f"Invalid timezone: {tz}") from exc

        if current_date:
            if isinstance(current_date, date):
                ref_date = current_date
            else:
                try:
                    ref_date = date.fromisoformat(str(current_date).strip())
                except ValueError as exc:
                    raise APIError(422, "validation_error", f"Invalid calendar date: {current_date}") from exc
        else:
            ref_date = datetime.now(zone).date()

        # 2. Retrieve or Create Session
        session: ConversationSession | None = None
        if conversation_id:
            session = self.get_session(conversation_id)
        elif not conversation_id:
            session = self.get_active_session_for_user(user.id)

        if not session or session.state in (ConversationState.COMPLETED, ConversationState.CANCELLED):
            cid = conversation_id or str(uuid.uuid4())
            session = ConversationSession(id=cid, user_id=user.id)
            self._sessions[cid] = session
            self._user_active_sessions[user.id] = cid

        session.mode = mode

        # Update activity timestamp & history
        session.updated_at = datetime.now(timezone.utc)
        session.history.append({"role": "user", "content": clean_text})

        # 3. Analyze Input Intent
        lower = clean_text.lower()
        normalized = re.sub(r"[^\w\s]", "", lower).strip()

        # Check Pending Plan Query (e.g. "Do I have pending plans?")
        if is_pending_plan_query(clean_text):
            if session.state == ConversationState.AWAITING_CONFIRMATION and session.pending_plan and session.pending_plan.title:
                summary = format_confirmation_summary(session.pending_plan, ref_date)
                reply = f"Yes, you have a pending plan: '{summary}' Press 1 to confirm or 2 to cancel."
                session.last_assistant_message = reply
                return ConversationTurnResult(
                    conversation_id=session.id,
                    state=session.state,
                    reply_text=reply,
                    prompt_type="info",
                    pending_plan=session.pending_plan.model_dump(),
                    proposal={"id": session.proposal_id} if session.proposal_id else None,
                    needs_button=True,
                )
            else:
                reply = "You have no pending plans waiting for confirmation."
                session.last_assistant_message = reply
                return ConversationTurnResult(
                    conversation_id=session.id,
                    state=session.state,
                    reply_text=reply,
                    prompt_type="info",
                    pending_plan=None,
                    needs_button=False,
                )

        # Check Coach Mode handling
        is_coach_active = (
            mode == "coach"
            or session.mode == "coach"
            or session.state in (
                ConversationState.COACH_RECOMMENDING,
                ConversationState.COACH_AWAITING_TIME_CHANGE,
                ConversationState.COACH_COLLECTING_TIME,
            )
        )
        is_rec_query = bool(
            re.search(r"\b(recommend|coach|suggestion|suggest|idea|öner|oner|tavsiye)\b", lower)
        )
        is_confirmed_trigger = (
            normalized in CONFIRMATION_PATTERNS
            or any(
                p in normalized
                for p in ("yes please", "create it", "save it", "looks good", "sounds good", "go ahead", "please confirm", "yes confirm", "confirm it")
            )
        )
        if (is_coach_active or is_rec_query) and session.state in (
            ConversationState.COLLECTING_DETAILS,
            ConversationState.COACH_RECOMMENDING,
            ConversationState.COACH_AWAITING_TIME_CHANGE,
            ConversationState.COACH_COLLECTING_TIME,
        ) and not (is_confirmed_trigger and session.state == ConversationState.AWAITING_CONFIRMATION):
            coach_turn = self._handle_coach_turn(
                session=session,
                user=user,
                clean_text=clean_text,
                store=store,
                ref_date=ref_date,
                zone=zone,
                idempotency_key=idempotency_key,
                source=source,
            )
            if coach_turn is not None:
                return coach_turn
        normalized = re.sub(r"[^\w\s]", "", lower).strip()

        # A. Check Confirmation
        # A. Check Confirmation
        is_confirmation = (
            normalized in CONFIRMATION_PATTERNS
            or any(
                p in normalized
                for p in ("yes please", "create it", "save it", "looks good", "sounds good", "go ahead", "please confirm", "yes confirm")
            )
            or (session.state == ConversationState.AWAITING_CONFIRMATION and (normalized == "yes" or normalized.startswith("yes ")))
        )
        if is_confirmation:
            if session.state == ConversationState.AWAITING_CONFIRMATION:
                return self._handle_confirmation(session, user, store, ref_date, zone, source, idempotency_key)
            elif session.state == ConversationState.COMPLETED and session.created_plan:
                # Repeated confirmation of already completed plan (idempotent replay)
                reply = f"Your plan to {session.pending_plan.title} is already confirmed and scheduled."
                return ConversationTurnResult(
                    conversation_id=session.id,
                    state=ConversationState.COMPLETED,
                    reply_text=reply,
                    prompt_type="success",
                    pending_plan=session.pending_plan.model_dump(),
                    plan=session.created_plan,
                    needs_button=False,
                )
            elif session.state in (ConversationState.COLLECTING_DETAILS, ConversationState.AWAITING_CLARIFICATION):
                # Do not treat a clarification answer as permission to save
                clarification = session.pending_plan.clarification_question or "What time would you like to start?"
                reply = f"Before I can confirm, {clarification.lower() if clarification.endswith('?') else clarification}"
                return ConversationTurnResult(
                    conversation_id=session.id,
                    state=session.state,
                    reply_text=reply,
                    prompt_type="clarification",
                    pending_plan=session.pending_plan.model_dump(),
                    needs_button=False,
                )

        # B. Check Cancellation
        # (Exclude corrections like "No, I meant 5 AM")
        is_correction_no = bool(re.search(r"\bno,?\s+(?:i\s+meant|change|make|not)\b", lower)) or bool(re.search(r"\b(?:am|pm|\d{1,2})\b", lower) and "meant" in lower)
        is_cancellation = not is_correction_no and (
            normalized in CANCELLATION_PATTERNS
            or any(
                p in normalized
                for p in ("cancel that", "cancel it", "no cancel", "dont save", "dont create", "never mind", "abort", "discard", "no cancel that")
            )
            or normalized.startswith("cancel")
            or (session.state == ConversationState.AWAITING_CONFIRMATION and (normalized == "no" or normalized.startswith("no ")))
        )
        if is_cancellation:
            if session.state in (
                ConversationState.AWAITING_CONFIRMATION,
                ConversationState.AWAITING_CLARIFICATION,
                ConversationState.COLLECTING_DETAILS,
            ):
                return self._handle_cancellation(session, user, store)

        # C. Check Corrections or Clarification Answers to an existing pending plan
        is_pending = session.state in (
            ConversationState.AWAITING_CONFIRMATION,
            ConversationState.AWAITING_CLARIFICATION,
            ConversationState.COLLECTING_DETAILS,
        ) and (session.pending_plan.title is not None)

        # C1. Check explicit "AM" or "PM" answer to previous AM/PM clarification
        if session.ambiguous_hour is not None:
            # First check if text contains an explicit time like "2 AM", "2 PM", "2 a.m.", "2 p.m.", "3 PM"
            resolved_t, resolved_ambig, _ = extract_time_and_ambiguity(clean_text)
            if resolved_t is not None and not resolved_ambig:
                session.pending_plan.time = resolved_t
                session.pending_plan.time_is_ambiguous = False
                session.ambiguous_hour = None
                session.last_clarification_field = None
                return self._evaluate_and_transition(session, user, store, ref_date)

            ampm_norm = re.sub(r"\b([ap])\.m\.?", r"\1m", lower)
            ampm_norm = re.sub(r"[^\w\s]", "", ampm_norm).strip()
            if any(p in ampm_norm for p in ("pm", "afternoon", "evening", "night")):
                h = session.ambiguous_hour
                if h < 12:
                    h += 12
                session.pending_plan.time = f"{h:02d}:00"
                session.pending_plan.time_is_ambiguous = False
                session.ambiguous_hour = None
                session.last_clarification_field = None
                return self._evaluate_and_transition(session, user, store, ref_date)
            elif any(p in ampm_norm for p in ("am", "morning")):
                h = session.ambiguous_hour
                if h == 12:
                    h = 0
                session.pending_plan.time = f"{h:02d}:00"
                session.pending_plan.time_is_ambiguous = False
                session.ambiguous_hour = None
                session.last_clarification_field = None
                return self._evaluate_and_transition(session, user, store, ref_date)

        # C2. Check contextual duration answer (e.g. "Thirty", "30", "forty-five")
        if is_awaiting_duration_clarification(session):
            dur_ctx = extract_contextual_duration(clean_text)
            if dur_ctx is not None:
                session.pending_plan.duration_minutes = dur_ctx
                session.last_clarification_field = None
                return self._evaluate_and_transition(session, user, store, ref_date)

        # C3. Check time expression in text
        time_val, is_ambig, ambig_hour = extract_time_and_ambiguity(clean_text)
        if is_ambig:
            session.pending_plan.time_is_ambiguous = True
            session.ambiguous_hour = ambig_hour
        elif time_val is not None:
            session.pending_plan.time = time_val
            session.pending_plan.time_is_ambiguous = False
            session.ambiguous_hour = None

        # C4. Check duration correction (e.g. "make it two hours", "for two hours")
        dur_val = extract_duration_minutes(clean_text)
        if dur_val is not None:
            session.pending_plan.duration_minutes = dur_val

        # C5. Check date correction (e.g. "not tomorrow, Friday", "change to Friday", "tomorrow")
        date_val = resolve_relative_date(clean_text, ref_date)
        if date_val is not None:
            session.pending_plan.date = date_val.isoformat()

        # If parsed_plan specifies a task title, update it
        new_title = parsed_plan.root.get("title") if parsed_plan and isinstance(parsed_plan.root, dict) else None
        if new_title:
            session.pending_plan.title = new_title
            session.pending_plan.category = parsed_plan.root.get("category", "other")
        elif is_pending and (time_val is not None or dur_val is not None or date_val is not None or is_ambig):
            return self._evaluate_and_transition(session, user, store, ref_date)

        # D. New Request or Full Utterance Extraction
        # Run AI-assisted interpretation pipeline
        parsed = parsed_plan
        if parsed is None:
            try:
                parsed = parse_text(
                    text=clean_text,
                    current_date=ref_date,
                    timezone=tz,
                    language="en",
                    llm_client=llm_client,
                )
            except Exception as exc:
                logger.warning("LLM parse_text failed or unavailable: %s", exc)
                parsed = None

        if parsed:
            p_dict = parsed.root
            intent = p_dict.get("intent")

            # Check if this is an unsupported query
            if intent == "unsupported":
                if is_pending:
                    # Preserve existing pending plan without overwriting or confirming
                    summary = format_confirmation_summary(session.pending_plan, ref_date)
                    msg = (
                        f"I can only help with scheduling plans. Your pending plan: '{summary}' "
                        f"is waiting for your confirmation. Would you like to confirm, correct details, or cancel?"
                    )
                    return ConversationTurnResult(
                        conversation_id=session.id,
                        state=session.state,
                        reply_text=msg,
                        prompt_type="info",
                        pending_plan=session.pending_plan.model_dump(),
                        needs_button=(session.state == ConversationState.AWAITING_CONFIRMATION),
                    )
                else:
                    reply = "I can help you create and schedule plans. Please describe the activity you'd like to plan, including the date and time."
                    return ConversationTurnResult(
                        conversation_id=session.id,
                        state=ConversationState.UNSUPPORTED,
                        reply_text=reply,
                        prompt_type="unsupported",
                        pending_plan=None,
                        needs_button=False,
                    )
            elif intent == "clarify":
                if p_dict.get("title"):
                    session.pending_plan.title = p_dict["title"]
                if p_dict.get("category"):
                    session.pending_plan.category = p_dict["category"]
                if p_dict.get("date"):
                    session.pending_plan.date = p_dict["date"]
                elif date_val is not None:
                    session.pending_plan.date = date_val.isoformat()
                if p_dict.get("time"):
                    session.pending_plan.time = p_dict["time"]
                elif time_val is not None:
                    session.pending_plan.time = time_val

                if p_dict.get("duration_minutes"):
                    session.pending_plan.duration_minutes = p_dict["duration_minutes"]
                elif dur_val is not None:
                    session.pending_plan.duration_minutes = dur_val
                else:
                    session.pending_plan.duration_minutes = None

                if is_ambig:
                    session.pending_plan.time_is_ambiguous = True
                    session.ambiguous_hour = ambig_hour

                if not session.pending_plan.title:
                    self._fallback_extract(clean_text, session, ref_date)

                if session.pending_plan.time_is_ambiguous and session.ambiguous_hour is not None:
                    clarify_q = f"Do you mean {session.ambiguous_hour} AM or {session.ambiguous_hour} PM?"
                    session.last_clarification_field = "time"
                else:
                    clarify_q = p_dict.get("clarification_question") or "Could you please provide more details?"
                    lower_q = clarify_q.lower()
                    if "duration" in lower_q or "how long" in lower_q or "minutes" in lower_q or "how many hours" in lower_q:
                        session.last_clarification_field = "duration"
                    elif "time" in lower_q or "when" in lower_q or "am or" in lower_q:
                        session.last_clarification_field = "time"
                    elif "day" in lower_q or "date" in lower_q:
                        session.last_clarification_field = "date"

                session.state = ConversationState.AWAITING_CLARIFICATION
                session.pending_plan.clarification_question = clarify_q
                session.last_assistant_message = clarify_q

                return ConversationTurnResult(
                    conversation_id=session.id,
                    state=session.state,
                    reply_text=clarify_q,
                    prompt_type="clarification",
                    pending_plan=session.pending_plan.model_dump(),
                    needs_button=False,
                )

            # Apply extracted fields to pending plan
            if p_dict.get("title"):
                session.pending_plan.title = p_dict["title"]
            if p_dict.get("category"):
                session.pending_plan.category = p_dict["category"]
            if p_dict.get("date"):
                session.pending_plan.date = p_dict["date"]
            elif date_val is not None:
                session.pending_plan.date = date_val.isoformat()
            if p_dict.get("duration_minutes"):
                session.pending_plan.duration_minutes = p_dict["duration_minutes"]
            elif dur_val is not None:
                session.pending_plan.duration_minutes = dur_val
            if p_dict.get("needs_weather_check") is not None:
                session.pending_plan.needs_weather_check = p_dict["needs_weather_check"]
            if p_dict.get("recurrence"):
                session.pending_plan.recurrence = p_dict["recurrence"]

            # Respect deterministic time check if we already extracted time above
            if time_val is None and not is_ambig and p_dict.get("time"):
                session.pending_plan.time = p_dict["time"]

            # If user text had ambiguous hour like "at 5"
            if is_ambig:
                session.pending_plan.time_is_ambiguous = True
                session.ambiguous_hour = ambig_hour
            elif time_val is not None:
                session.pending_plan.time = time_val
                session.pending_plan.time_is_ambiguous = False

            if not session.pending_plan.title:
                self._fallback_extract(clean_text, session, ref_date)
        else:
            # Fallback deterministic extraction for offline/mock environments
            self._fallback_extract(clean_text, session, ref_date)

        return self._evaluate_and_transition(session, user, store, ref_date)

    def _fallback_extract(self, text: str, session: ConversationSession, ref_date: date) -> None:
        """Deterministic fallback field extraction if LLM is offline or in unit tests."""
        lower = text.lower()

        # Extract title / task
        # Check specific multi-word activity phrases first
        for phrase, word, cat in [
            ("go for a walk", "Walk", "sport"),
            ("take a walk", "Walk", "sport"),
            ("for a walk", "Walk", "sport"),
            ("go for a run", "Run", "sport"),
            ("take a run", "Run", "sport"),
            ("study math", "Study Math", "study"),
        ]:
            if phrase in lower:
                session.pending_plan.title = word
                session.pending_plan.category = cat
                break
        if not session.pending_plan.title:
            for task_word, cat in [
                ("walking", "sport"),
                ("walk", "sport"),
                ("swimming", "sport"),
                ("swim", "sport"),
                ("running", "sport"),
                ("run", "sport"),
                ("workout", "sport"),
                ("exercise", "sport"),
                ("yoga", "sport"),
                ("reading", "study"),
                ("read", "study"),
                ("study", "study"),
                ("meeting", "meeting"),
                ("code", "work"),
                ("work", "work"),
                ("dinner", "social"),
                ("lunch", "social"),
                ("meditate", "health"),
                ("meditation", "health"),
                ("koşu", "sport"),
                ("yürüyüş", "sport"),
            ]:
                if re.search(rf"\b{task_word}\b", lower):
                    session.pending_plan.title = task_word.title()
                    session.pending_plan.category = cat
                    break
        if not session.pending_plan.title:
            session.pending_plan.title = "Activity"
            session.pending_plan.category = "personal"

        # Extract date
        d = resolve_relative_date(text, ref_date)
        if d:
            session.pending_plan.date = d.isoformat()

        # Extract duration
        dur = extract_duration_minutes(text)
        if dur:
            session.pending_plan.duration_minutes = dur

        # Extract time
        t, ambig, amb_h = extract_time_and_ambiguity(text)
        if ambig:
            session.pending_plan.time_is_ambiguous = True
            session.ambiguous_hour = amb_h
        elif t:
            session.pending_plan.time = t
            session.pending_plan.time_is_ambiguous = False

    def _evaluate_and_transition(
        self,
        session: ConversationSession,
        user: AuthenticatedUser,
        store: PlanStore,
        current_date: date,
    ) -> ConversationTurnResult:
        """Checks pending plan completeness and transitions conversation state."""
        pending = session.pending_plan

        # 1. Ambiguous AM/PM check
        if pending.time_is_ambiguous and session.ambiguous_hour is not None:
            session.state = ConversationState.AWAITING_CLARIFICATION
            session.last_clarification_field = "time"
            clarify_q = f"Do you mean {session.ambiguous_hour} AM or {session.ambiguous_hour} PM?"
            pending.clarification_question = clarify_q
            session.last_assistant_message = clarify_q
            return ConversationTurnResult(
                conversation_id=session.id,
                state=session.state,
                reply_text=clarify_q,
                prompt_type="clarification",
                pending_plan=pending.model_dump(),
                needs_button=False,
            )

        # 2. Missing Start Time check
        if not pending.time:
            session.state = ConversationState.AWAITING_CLARIFICATION
            session.last_clarification_field = "time"
            clarify_q = "What time would you like to start?"
            pending.clarification_question = clarify_q
            session.last_assistant_message = clarify_q
            return ConversationTurnResult(
                conversation_id=session.id,
                state=session.state,
                reply_text=clarify_q,
                prompt_type="clarification",
                pending_plan=pending.model_dump(),
                needs_button=False,
            )

        # 3. Missing Date check
        if not pending.date:
            session.state = ConversationState.AWAITING_CLARIFICATION
            session.last_clarification_field = "date"
            clarify_q = "What day would you like to schedule this for?"
            pending.clarification_question = clarify_q
            session.last_assistant_message = clarify_q
            return ConversationTurnResult(
                conversation_id=session.id,
                state=session.state,
                reply_text=clarify_q,
                prompt_type="clarification",
                pending_plan=pending.model_dump(),
                needs_button=False,
            )

        # 4. Missing Duration check (when pending.duration_minutes is None)
        if pending.duration_minutes is None:
            session.state = ConversationState.AWAITING_CLARIFICATION
            session.last_clarification_field = "duration"
            clarify_q = "How long would you like to schedule this for?"
            pending.clarification_question = clarify_q
            session.last_assistant_message = clarify_q
            return ConversationTurnResult(
                conversation_id=session.id,
                state=session.state,
                reply_text=clarify_q,
                prompt_type="clarification",
                pending_plan=pending.model_dump(),
                needs_button=False,
            )

        # 5. All essential details are present -> Awaiting Confirmation
        session.state = ConversationState.AWAITING_CONFIRMATION
        session.last_clarification_field = None
        pending.clarification_question = None

        # Regenerate fresh idempotency key for this specific plan configuration
        session.idempotency_key = str(uuid.uuid4())

        # Sync with plan_proposals table so physical ESP32 buttons (Btn 1 / 2) work
        proposal_dict = self._sync_plan_proposal(session, user, store)

        summary = format_confirmation_summary(pending, current_date)
        session.last_assistant_message = summary

        return ConversationTurnResult(
            conversation_id=session.id,
            state=session.state,
            reply_text=summary,
            prompt_type="confirmation",
            pending_plan=pending.model_dump(),
            proposal=proposal_dict,
            needs_button=True,
        )

    def _sync_plan_proposal(
        self,
        session: ConversationSession,
        user: AuthenticatedUser,
        store: PlanStore,
    ) -> dict[str, Any] | None:
        """Creates or updates a proposal record in store for hardware button integration."""
        pending = session.pending_plan
        if not pending.date or not pending.time:
            return None

        try:
            zone = ZoneInfo(user.timezone or SCHEDULING_TIMEZONE)
            p_date = date.fromisoformat(pending.date)
            p_time = time.fromisoformat(pending.time)
            start = datetime.combine(p_date, p_time, tzinfo=zone)
            duration = pending.duration_minutes or 60
            end = start + timedelta(minutes=duration)

            proposal_record = {
                "title": pending.title or "Plan",
                "category": pending.category or "other",
                "planned_start": start.isoformat(),
                "planned_end": end.isoformat(),
                "duration_minutes": duration,
                "recurrence_rule": pending.recurrence,
            }

            if hasattr(store, "create_plan_proposal"):
                prop = store.create_plan_proposal(
                    user_id=user.id,
                    proposal=proposal_record,
                    conversation_id=session.id,
                )
                session.proposal_id = str(prop["id"])
                return prop
        except Exception as exc:
            logger.warning("Could not sync plan proposal: %s", exc)

        return None

    def _handle_confirmation(
        self,
        session: ConversationSession,
        user: AuthenticatedUser,
        store: PlanStore,
        ref_date: date,
        zone: ZoneInfo,
        source: str,
        idempotency_key: str | None,
    ) -> ConversationTurnResult:
        """Persists the confirmed plan exactly once."""
        pending = session.pending_plan
        if not pending.date or not pending.time or not pending.title:
            raise APIError(422, "validation_error", "Cannot confirm plan with missing details.")

        p_date = date.fromisoformat(pending.date)
        p_time = time.fromisoformat(pending.time)
        start = datetime.combine(p_date, p_time, tzinfo=zone)
        duration = pending.duration_minutes or 60
        end = start + timedelta(minutes=duration)

        plan_record = {
            "user_id": user.id,
            "title": pending.title,
            "category": pending.category or "other",
            "planned_start": start.isoformat(),
            "planned_end": end.isoformat(),
            "recurrence_rule": pending.recurrence,
            "source": source,
        }

        active_key = idempotency_key or session.idempotency_key or str(uuid.uuid4())
        session.idempotency_key = active_key

        canonical_hash = hashlib.sha256(
            json.dumps(plan_record, sort_keys=True).encode("utf-8")
        ).hexdigest()

        try:
            if session.proposal_id and hasattr(store, "accept_plan_proposal"):
                _, created_plan = store.accept_plan_proposal(
                    user_id=user.id, proposal_id=session.proposal_id
                )
            elif hasattr(store, "create_plan_idempotently"):
                created_plan, conflict = store.create_plan_idempotently(
                    user_id=user.id,
                    idempotency_key=active_key,
                    request_hash=canonical_hash,
                    plan=plan_record,
                )
                if conflict:
                    raise APIError(422, "validation_error", "Idempotency key collision on plan creation.")
            else:
                created_plan = store.create_plan(plan_record)
        except APIError:
            raise
        except Exception as exc:
            logger.exception("Failed to persist confirmed plan: %s", exc)
            # Never claim success if persistence fails
            raise HTTPException(status_code=500, detail="Failed to save the plan. Please try again.") from exc

        # Mark session completed
        session.state = ConversationState.COMPLETED
        session.created_plan_id = str(created_plan["id"])
        session.created_plan = created_plan
        self.clear_active_session_for_user(user.id)

        # Record accepted feedback for coach recommendation if applicable
        if session.current_recommendation and hasattr(store, "save_recommendation_feedback"):
            try:
                store.save_recommendation_feedback(user.id, {
                    "recommendation_id": session.current_recommendation["id"],
                    "action": "accepted",
                })
            except Exception as exc:
                logger.warning("Could not record accepted feedback for coach recommendation: %s", exc)

        time_12h = p_time.strftime("%I:%M %p").lstrip("0")
        reply = sanitize_for_speech(
            f"Great! Your plan to {pending.title.lower()} at {time_12h} has been confirmed and saved to your schedule."
        )
        session.last_assistant_message = reply

        return ConversationTurnResult(
            conversation_id=session.id,
            state=session.state,
            reply_text=reply,
            prompt_type="success",
            pending_plan=pending.model_dump(),
            plan=created_plan,
            recommendation=session.current_recommendation,
            needs_button=False,
        )

    def _handle_cancellation(
        self,
        session: ConversationSession,
        user: AuthenticatedUser,
        store: PlanStore,
    ) -> ConversationTurnResult:
        """Discards pending plan without saving to database."""
        session.state = ConversationState.CANCELLED
        self.clear_active_session_for_user(user.id)

        # Reject proposal in store if one was created
        if session.proposal_id and hasattr(store, "reject_plan_proposal"):
            try:
                store.reject_plan_proposal(user_id=user.id, proposal_id=session.proposal_id)
            except Exception:
                pass

        title = session.pending_plan.title or "plan"
        reply = sanitize_for_speech(f"The plan draft for {title} has been cancelled.")
        session.last_assistant_message = reply

        return ConversationTurnResult(
            conversation_id=session.id,
            state=session.state,
            reply_text=reply,
            prompt_type="cancellation",
            pending_plan=session.pending_plan.model_dump(),
            needs_button=False,
        )

    def _refresh_recommendation_pool(
        self,
        session: ConversationSession,
        user: AuthenticatedUser,
        store: PlanStore,
        ref_date: date,
    ) -> list[dict[str, Any]]:
        history = store.list_plans(user_id=user.id) if hasattr(store, "list_plans") else []
        outcomes = store.list_outcomes(user_id=user.id) if hasattr(store, "list_outcomes") else []
        profile = store.get_personalization(user_id=user.id) if hasattr(store, "get_personalization") else {}
        feedback = store.list_recommendation_feedback(user.id) if hasattr(store, "list_recommendation_feedback") else []
        now_utc = datetime.now(timezone.utc)
        behavior = calculate_recommendations(history, outcomes, user_timezone=user.timezone)
        contextual = build_contextual_recommendations(
            profile=profile, plans=history, now=now_utc, timezone_name=user.timezone, outcomes=outcomes
        )
        recs = apply_policy(behavior, feedback, contextual=contextual, now=now_utc)
        session.recommendations_pool = recs
        return recs

    def _get_next_recommendation(
        self,
        session: ConversationSession,
        user: AuthenticatedUser,
        store: PlanStore,
        ref_date: date,
    ) -> dict[str, Any] | None:
        if not session.recommendations_pool:
            self._refresh_recommendation_pool(session, user, store, ref_date)
        for r in session.recommendations_pool:
            if r["id"] not in session.shown_recommendation_ids:
                return r
        # If pool has been shown, check discovery ideas not yet shown to cycle through them
        from app.recommendations import DISCOVERY_IDEAS
        for disc in DISCOVERY_IDEAS:
            if disc["id"] not in session.shown_recommendation_ids:
                candidate = dict(
                    disc,
                    source="discovery",
                    label="Not based on your history",
                    why="Starter idea; not based on your history.",
                    confidence="none",
                    evidence={},
                    next_step=disc["message"],
                )
                session.recommendations_pool.append(candidate)
                return candidate
        return None

    def _handle_coach_turn(
        self,
        session: ConversationSession,
        user: AuthenticatedUser,
        clean_text: str,
        store: PlanStore,
        ref_date: date,
        zone: ZoneInfo,
        idempotency_key: str | None = None,
        source: str = "voice",
    ) -> ConversationTurnResult | None:
        lower = clean_text.lower()
        norm = re.sub(r"[^\w\s]", "", lower).strip()

        # 1. In COACH_RECOMMENDING: User can Dislike, Like, or change topic
        if session.state == ConversationState.COACH_RECOMMENDING:
            is_dislike = (
                norm in (
                    "i dont like it", "i don't like it", "dont like it", "dislike",
                    "something else", "another", "next", "begenmedim", "beğenmedim",
                    "baska oner", "başka öner", "baska", "başka", "not interested",
                    "show another", "show another idea", "pass", "no", "nope",
                )
                or any(
                    p in norm
                    for p in (
                        "dont like", "don't like", "begenmedim", "beğenmedim",
                        "baska oner", "başka öner", "something else", "another idea",
                        "show another", "not interested",
                    )
                )
            )
            if is_dislike:
                # Record dismissal feedback immediately
                if session.current_recommendation and hasattr(store, "save_recommendation_feedback"):
                    try:
                        store.save_recommendation_feedback(user.id, {
                            "recommendation_id": session.current_recommendation["id"],
                            "action": "dismissed",
                        })
                    except Exception as exc:
                        logger.warning("Could not save dismissal feedback: %s", exc)

                next_rec = self._get_next_recommendation(session, user, store, ref_date)
                is_tr = bool(re.search(r"\b(baska|başka|begen|beğen)\b", norm))
                if next_rec:
                    session.current_recommendation = next_rec
                    session.shown_recommendation_ids.append(next_rec["id"])
                    prefix = "Yeni bir öneri: " if is_tr else "How about this: "
                    reply = f"{prefix}{next_rec['title']}. {next_rec['message']}"
                    session.last_assistant_message = reply
                    return ConversationTurnResult(
                        conversation_id=session.id,
                        state=session.state,
                        reply_text=reply,
                        prompt_type="coach_recommendation",
                        recommendation=next_rec,
                        needs_button=False,
                    )
                else:
                    self._refresh_recommendation_pool(session, user, store, ref_date)
                    next_rec = self._get_next_recommendation(session, user, store, ref_date)
                    if next_rec:
                        session.current_recommendation = next_rec
                        session.shown_recommendation_ids.append(next_rec["id"])
                        prefix = "Yeni öneriler buluyorum. " if is_tr else "Finding new recommendations. How about this: "
                        reply = f"{prefix}{next_rec['title']}. {next_rec['message']}"
                        session.last_assistant_message = reply
                        return ConversationTurnResult(
                            conversation_id=session.id,
                            state=session.state,
                            reply_text=reply,
                            prompt_type="coach_recommendation",
                            recommendation=next_rec,
                            needs_button=False,
                        )
                    else:
                        reply = (
                            "Şu anda başka öneri bulunamadı. Yapmak istediğin aktiviteyi söyleyebilirsin!"
                            if is_tr
                            else "No more recommendations available right now. Tell me any activity you'd like to plan!"
                        )
                        session.last_assistant_message = reply
                        return ConversationTurnResult(
                            conversation_id=session.id,
                            state=ConversationState.COLLECTING_DETAILS,
                            reply_text=reply,
                            prompt_type="info",
                            needs_button=False,
                        )

            has_negation = any(neg in norm for neg in ("dont", "not", "dislike", "begenme", "beğenme", "hayir", "hayır"))
            is_like = (not has_negation) and (
                norm in (
                    "i like it", "like it", "i like this", "like this",
                    "bunu yapalim", "bunu yapalım", "begendim", "beğendim",
                    "sounds good", "let's do this", "lets do this", "great",
                    "perfect", "good idea", "yes please", "sure", "love it",
                )
                or any(
                    p in norm
                    for p in (
                        "like it", "like this", "bunu yapalim", "bunu yapalım",
                        "begendim", "beğendim", "sounds good", "lets do this", "let's do this",
                    )
                )
            )
            if is_like:
                session.state = ConversationState.COACH_AWAITING_TIME_CHANGE
                is_tr = bool(re.search(r"\b(evet|bunu|yap|beğen|begendim)\b", norm))
                reply = (
                    "Bu öneri için tarih veya saatini değiştirmek ister misin?"
                    if is_tr
                    else "Would you like to change the date or time for this recommendation?"
                )
                session.last_assistant_message = reply
                return ConversationTurnResult(
                    conversation_id=session.id,
                    state=session.state,
                    reply_text=reply,
                    prompt_type="coach_time_choice",
                    recommendation=session.current_recommendation,
                    needs_button=False,
                )

        # 2. In COACH_AWAITING_TIME_CHANGE: User decides whether to change time
        if session.state == ConversationState.COACH_AWAITING_TIME_CHANGE:
            is_no = (
                norm in (
                    "no", "no thanks", "no change", "keep it", "same", "default is fine",
                    "leave it", "hayir", "hayır", "aynen kalsin", "aynen kalsın", "gerek yok", "aynen",
                )
                or norm.startswith("no ")
                or norm.startswith("hayir ")
                or norm.startswith("hayır ")
            )
            rec = session.current_recommendation or {}
            dur = rec.get("duration_minutes") or 30

            if is_no:
                session.pending_plan.title = rec.get("title") or "Activity"
                session.pending_plan.category = rec.get("category") or "personal"
                session.pending_plan.date = ref_date.isoformat()
                session.pending_plan.time = "18:00"
                session.pending_plan.duration_minutes = dur

                session.state = ConversationState.AWAITING_CONFIRMATION
                proposal_dict = self._sync_plan_proposal(session, user, store)
                is_tr = bool(re.search(r"\b(hayir|hayır|aynen|gerek)\b", norm))
                summary = (
                    f"Plan: Bugün 18:00'de {dur} dakika {session.pending_plan.title}. Onaylamak için 1'e, iptal için 2'ye basın."
                    if is_tr
                    else f"Plan: {session.pending_plan.title} today at 6:00 PM for {dur} minutes. Press 1 to confirm or 2 to cancel."
                )
                session.last_assistant_message = summary
                return ConversationTurnResult(
                    conversation_id=session.id,
                    state=session.state,
                    reply_text=summary,
                    prompt_type="confirmation",
                    pending_plan=session.pending_plan.model_dump(),
                    proposal=proposal_dict,
                    recommendation=rec,
                    needs_button=True,
                )

            # Check if user said Yes and included date/time directly (e.g. "Yes, make it tomorrow at 5 PM")
            t_val, is_amb, amb_h = extract_time_and_ambiguity(clean_text)
            d_val = resolve_relative_date(clean_text, ref_date)
            dur_val = extract_duration_minutes(clean_text)

            if t_val or d_val or dur_val:
                session.pending_plan.title = rec.get("title") or "Activity"
                session.pending_plan.category = rec.get("category") or "personal"
                session.pending_plan.date = (d_val or ref_date).isoformat()
                session.pending_plan.time = t_val or "18:00"
                session.pending_plan.duration_minutes = dur_val or dur

                session.state = ConversationState.AWAITING_CONFIRMATION
                proposal_dict = self._sync_plan_proposal(session, user, store)
                p_date = date.fromisoformat(session.pending_plan.date)
                day_name = p_date.strftime("%A")
                p_time = time.fromisoformat(session.pending_plan.time)
                time_12h = p_time.strftime("%I:%M %p").lstrip("0")
                summary = (
                    f"Plan: {session.pending_plan.title} on {day_name} at {time_12h} for {session.pending_plan.duration_minutes} minutes. Confirm to schedule?"
                )
                session.last_assistant_message = summary
                return ConversationTurnResult(
                    conversation_id=session.id,
                    state=session.state,
                    reply_text=summary,
                    prompt_type="confirmation",
                    pending_plan=session.pending_plan.model_dump(),
                    proposal=proposal_dict,
                    recommendation=rec,
                    needs_button=True,
                )
            else:
                # User said Yes without specifying details yet
                session.state = ConversationState.COACH_COLLECTING_TIME
                is_tr = bool(re.search(r"\b(evet|degistir|değiştir)\b", norm))
                reply = (
                    "Hangi gün ve saatte planlamak istersin?"
                    if is_tr
                    else "What date and time would you like to schedule it for?"
                )
                session.last_assistant_message = reply
                return ConversationTurnResult(
                    conversation_id=session.id,
                    state=session.state,
                    reply_text=reply,
                    prompt_type="clarification",
                    recommendation=rec,
                    needs_button=False,
                )

        # 3. In COACH_COLLECTING_TIME: User provides date/time for the recommendation
        if session.state == ConversationState.COACH_COLLECTING_TIME:
            t_val, is_amb, amb_h = extract_time_and_ambiguity(clean_text)
            d_val = resolve_relative_date(clean_text, ref_date)
            dur_val = extract_duration_minutes(clean_text)

            rec = session.current_recommendation or {}
            dur = dur_val or rec.get("duration_minutes") or 30

            if t_val or d_val:
                session.pending_plan.title = rec.get("title") or "Activity"
                session.pending_plan.category = rec.get("category") or "personal"
                session.pending_plan.date = (d_val or ref_date).isoformat()
                session.pending_plan.time = t_val or "18:00"
                session.pending_plan.duration_minutes = dur

                session.state = ConversationState.AWAITING_CONFIRMATION
                proposal_dict = self._sync_plan_proposal(session, user, store)
                p_date = date.fromisoformat(session.pending_plan.date)
                day_name = p_date.strftime("%A")
                p_time = time.fromisoformat(session.pending_plan.time)
                time_12h = p_time.strftime("%I:%M %p").lstrip("0")
                summary = (
                    f"Plan: {session.pending_plan.title} on {day_name} at {time_12h} for {session.pending_plan.duration_minutes} minutes. Confirm to schedule?"
                )
                session.last_assistant_message = summary
                return ConversationTurnResult(
                    conversation_id=session.id,
                    state=session.state,
                    reply_text=summary,
                    prompt_type="confirmation",
                    pending_plan=session.pending_plan.model_dump(),
                    proposal=proposal_dict,
                    recommendation=rec,
                    needs_button=True,
                )
            else:
                reply = "Please specify a time, like 5 PM or tomorrow at 6 PM."
                session.last_assistant_message = reply
                return ConversationTurnResult(
                    conversation_id=session.id,
                    state=session.state,
                    reply_text=reply,
                    prompt_type="clarification",
                    recommendation=rec,
                    needs_button=False,
                )

        # 4. In initial state / asking for recommendation
        is_rec_intent = bool(
            re.search(r"\b(recommend|coach|suggestion|idea|suggest|öner|oner|tavsiye)\b", lower)
        )
        if is_rec_intent:
            rec = self._get_next_recommendation(session, user, store, ref_date)
            if not rec:
                self._refresh_recommendation_pool(session, user, store, ref_date)
                rec = self._get_next_recommendation(session, user, store, ref_date)

            is_tr = bool(re.search(r"\b(oner|öner|tavsiye|selam|merhaba)\b", lower))
            if rec:
                session.current_recommendation = rec
                session.shown_recommendation_ids.append(rec["id"])
                session.state = ConversationState.COACH_RECOMMENDING
                prefix = "Günün önerisi: " if is_tr else "How about this: "
                reply = f"{prefix}{rec['title']}. {rec['message']}"
                session.last_assistant_message = reply
                return ConversationTurnResult(
                    conversation_id=session.id,
                    state=session.state,
                    reply_text=reply,
                    prompt_type="coach_recommendation",
                    recommendation=rec,
                    needs_button=False,
                )
            else:
                reply = (
                    "Şu anda yeni öneri bulunamadı. Yapmak istediğin planı söyleyebilirsin."
                    if is_tr
                    else "No recommendations are available right now. Tell me what you'd like to plan!"
                )
                session.last_assistant_message = reply
                return ConversationTurnResult(
                    conversation_id=session.id,
                    state=ConversationState.COLLECTING_DETAILS,
                    reply_text=reply,
                    prompt_type="info",
                    needs_button=False,
                )

        return None


_conversation_engine = ConversationEngine()


def get_conversation_engine() -> ConversationEngine:
    return _conversation_engine
