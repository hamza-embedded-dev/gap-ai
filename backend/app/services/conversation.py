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
from app.db.plans import AuthenticatedUser, PlanStore, get_plan_store
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
}

CANCELLATION_PATTERNS = {
    "cancel", "cancel that", "no", "no thanks", "don't create it", "don't create",
    "discard", "never mind", "stop", "abort", "2", "reject", "don't save",
    "nevermind", "cancel it", "no cancel",
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
    ambiguous_hour: int | None = None
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
    needs_button: bool = False


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


def extract_time_and_ambiguity(text: str) -> tuple[str | None, bool, int | None]:
    """Analyzes text for time expressions.

    Returns:
        (resolved_time_24h, is_ambiguous, ambiguous_hour)
        - If resolved_time_24h is set, returns HH:MM in 24h format.
        - If is_ambiguous is True, returns True and the 12-hour digit (e.g. 5).
    """
    lower = text.lower()

    # 1. Check for explicit AM/PM with digits or words:
    # "5 PM", "5:00 PM", "5:30 pm", "5pm", "5 am", "5am"
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

    # Words like "five pm", "five am"
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

    def __init__(self) -> None:
        self._sessions: dict[str, ConversationSession] = {}
        self._user_active_sessions: dict[str, str] = {}  # user_id -> conversation_id

    def get_session(self, conversation_id: str) -> ConversationSession | None:
        return self._sessions.get(conversation_id)

    def get_active_session_for_user(self, user_id: str) -> ConversationSession | None:
        cid = self._user_active_sessions.get(user_id)
        if not cid:
            return None
        sess = self._sessions.get(cid)
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
        if conversation_id and conversation_id in self._sessions:
            session = self._sessions[conversation_id]
        elif not conversation_id:
            session = self.get_active_session_for_user(user.id)

        if not session or session.state in (ConversationState.COMPLETED, ConversationState.CANCELLED):
            cid = conversation_id or str(uuid.uuid4())
            session = ConversationSession(id=cid, user_id=user.id)
            self._sessions[cid] = session
            self._user_active_sessions[user.id] = cid

        # Update activity timestamp & history
        session.updated_at = datetime.now(timezone.utc)
        session.history.append({"role": "user", "content": clean_text})

        # 3. Analyze Input Intent
        lower = clean_text.lower()
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
            if normalized in ("pm", "5 pm", "5pm", f"{session.ambiguous_hour} pm", f"{session.ambiguous_hour}pm") or "pm" in normalized:
                h = session.ambiguous_hour
                if h < 12:
                    h += 12
                session.pending_plan.time = f"{h:02d}:00"
                session.pending_plan.time_is_ambiguous = False
                session.ambiguous_hour = None
                return self._evaluate_and_transition(session, user, store, ref_date)
            elif normalized in ("am", "5 am", "5am", f"{session.ambiguous_hour} am", f"{session.ambiguous_hour}am") or "am" in normalized:
                h = session.ambiguous_hour
                if h == 12:
                    h = 0
                session.pending_plan.time = f"{h:02d}:00"
                session.pending_plan.time_is_ambiguous = False
                session.ambiguous_hour = None
                return self._evaluate_and_transition(session, user, store, ref_date)

        # C2. Check time expression in text
        time_val, is_ambig, ambig_hour = extract_time_and_ambiguity(clean_text)
        if is_ambig:
            session.pending_plan.time_is_ambiguous = True
            session.ambiguous_hour = ambig_hour
            session.state = ConversationState.AWAITING_CLARIFICATION
            clarify_q = f"Do you mean {ambig_hour} AM or {ambig_hour} PM?"
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
        elif time_val is not None:
            session.pending_plan.time = time_val
            session.pending_plan.time_is_ambiguous = False
            session.ambiguous_hour = None

        # C3. Check duration correction (e.g. "make it two hours", "for two hours")
        dur_val = extract_duration_minutes(clean_text)
        if dur_val is not None:
            session.pending_plan.duration_minutes = dur_val

        # C4. Check date correction (e.g. "not tomorrow, Friday", "change to Friday", "tomorrow")
        date_val = resolve_relative_date(clean_text, ref_date)
        if date_val is not None:
            session.pending_plan.date = date_val.isoformat()

        # If parsed_plan specifies a task title, update it
        new_title = parsed_plan.root.get("title") if parsed_plan and isinstance(parsed_plan.root, dict) else None
        if new_title:
            session.pending_plan.title = new_title
            session.pending_plan.category = parsed_plan.root.get("category", "other")
        elif is_pending and (time_val is not None or dur_val is not None or date_val is not None):
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

            # Apply extracted fields to pending plan
            if p_dict.get("title"):
                session.pending_plan.title = p_dict["title"]
            if p_dict.get("category"):
                session.pending_plan.category = p_dict["category"]
            if p_dict.get("date"):
                session.pending_plan.date = p_dict["date"]
            if p_dict.get("duration_minutes"):
                session.pending_plan.duration_minutes = p_dict["duration_minutes"]
            if p_dict.get("needs_weather_check") is not None:
                session.pending_plan.needs_weather_check = p_dict["needs_weather_check"]
            if p_dict.get("recurrence"):
                session.pending_plan.recurrence = p_dict["recurrence"]

            # Respect deterministic time check if we already extracted time above
            if time_val is None and p_dict.get("time"):
                session.pending_plan.time = p_dict["time"]

            # If user text had ambiguous hour like "at 5"
            if is_ambig:
                session.pending_plan.time_is_ambiguous = True
                session.ambiguous_hour = ambig_hour
            elif time_val is not None:
                session.pending_plan.time = time_val
                session.pending_plan.time_is_ambiguous = False
        else:
            # Fallback deterministic extraction for offline/mock environments
            self._fallback_extract(clean_text, session, ref_date)

        return self._evaluate_and_transition(session, user, store, ref_date)

    def _fallback_extract(self, text: str, session: ConversationSession, ref_date: date) -> None:
        """Deterministic fallback field extraction if LLM is offline or in unit tests."""
        lower = text.lower()

        # Extract title / task
        for task_word, cat in [
            ("study", "study"),
            ("run", "sport"),
            ("workout", "sport"),
            ("meeting", "meeting"),
            ("code", "work"),
            ("work", "work"),
            ("dinner", "social"),
            ("lunch", "social"),
        ]:
            if task_word in lower:
                session.pending_plan.title = task_word.capitalize()
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

        # 4. All essential details are present -> Awaiting Confirmation
        session.state = ConversationState.AWAITING_CONFIRMATION
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


_conversation_engine = ConversationEngine()


def get_conversation_engine() -> ConversationEngine:
    return _conversation_engine
