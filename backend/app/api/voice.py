from __future__ import annotations

from datetime import date, datetime, time, timedelta
import logging
from typing import Literal
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, File, Form, Header, Response, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field

from app.ai.llm import NebiusLLMClient, get_llm_client
from app.ai.stt import (
    GroqWhisperClient,
    STTConfigurationError,
    STTError,
    STTParseError,
    STTResponseError,
    STTTimeoutError,
    STTUnavailableError,
    STTValidationError,
    get_stt_client,
    pcm_to_wav,
)
from app.ai.tts import GroqTTSClient, TTSError, get_tts_client
from app.api.errors import APIError
from app.api.parse import parse_text
from app.api.plans import PlanResponse, current_user
from app.api.proposals import ProposalResponse
from app.api.suggestions import get_suggestion_for_plan
from app.config import get_settings
from app.db.plans import AuthenticatedUser, PlanStore, get_plan_store
from app.schemas.conversation import ConversationState
from app.schemas.parsed_plan import ParsedPlan
from app.services.conversation import ConversationEngine, get_conversation_engine

logger = logging.getLogger(__name__)

router = APIRouter()


def _wants_wav(accept: str | None) -> bool:
    return bool(accept and "audio/wav" in accept.lower())


def _header_text(text: str) -> str:
    return quote(text.strip(), safe="")


# 320 KB in binary bytes (320 * 1024 = 327,680 bytes)
# Provides headroom for standard WAV header while enforcing 10s audio limit.
MAX_AUDIO_BYTES: int = 320 * 1024
STREAM_CHUNK_SIZE: int = 64 * 1024

RAW_PCM_CONTENT_TYPES = {"audio/pcm", "audio/raw", "audio/l16"}
RAW_PCM_EXTENSIONS = (".pcm", ".raw")


def _is_declared_raw_pcm(content_type: str | None, filename: str | None) -> bool:
    if content_type and content_type.lower().strip() in RAW_PCM_CONTENT_TYPES:
        return True
    if filename and filename.lower().strip().endswith(RAW_PCM_EXTENSIONS):
        return True
    return False


class VoicePlanResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    transcript: str
    parsed_plan: ParsedPlan
    plan: PlanResponse | None = None
    proposal: ProposalResponse | None = None
    spoken_recommendation: str | None = Field(default=None, max_length=240)


class VoiceClarifyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transcript: str
    parsed_plan: ParsedPlan


async def _read_audio_stream_with_limit(audio: UploadFile, max_bytes: int = MAX_AUDIO_BYTES) -> bytes:
    """Reads uploaded audio stream chunk-by-chunk to bound memory usage and enforce size limit.

    Raises APIError(413, 'payload_too_large') as soon as max_bytes is exceeded.
    """
    chunks: list[bytes] = []
    total_bytes = 0

    while True:
        chunk = await audio.read(STREAM_CHUNK_SIZE)
        if not chunk:
            break
        total_bytes += len(chunk)
        if total_bytes > max_bytes:
            raise APIError(
                413,
                "payload_too_large",
                f"Audio payload exceeds maximum allowed size of {max_bytes} bytes (320 KB).",
            )
        chunks.append(chunk)

    audio_bytes = b"".join(chunks)
    if not audio_bytes:
        raise APIError(422, "validation_error", "Audio data is empty.")

    return audio_bytes


def _build_plan_record(
    parsed_plan: ParsedPlan,
    user: AuthenticatedUser,
) -> dict[str, object]:
    plan_dict = parsed_plan.root
    if plan_dict.get("intent") != "create_plan":
        raise APIError(422, "validation_error", "Only create_plan intents can be saved.")

    try:
        zone = ZoneInfo(user.timezone)
    except ZoneInfoNotFoundError as exc:
        raise APIError(422, "validation_error", "The user's timezone is invalid.") from exc

    try:
        plan_date = date.fromisoformat(str(plan_dict.get("date")))
        plan_time = time.fromisoformat(str(plan_dict.get("time")))
    except (ValueError, TypeError) as exc:
        raise APIError(422, "validation_error", "The plan date or time is invalid.") from exc

    start = datetime.combine(plan_date, plan_time, tzinfo=zone)
    duration = plan_dict.get("duration_minutes")
    end = start + timedelta(minutes=60 if duration is None else int(duration))

    return {
        "user_id": user.id,
        "title": plan_dict.get("title"),
        "category": plan_dict.get("category"),
        "planned_start": start.isoformat(),
        "planned_end": end.isoformat(),
        "recurrence_rule": plan_dict.get("recurrence"),
        "source": "voice",
    }


VOICE_LANGUAGE: Literal["en"] = "en"


@router.post(
    "/voice",
    response_model=VoicePlanResponse | VoiceClarifyResponse,
    status_code=status.HTTP_201_CREATED,
)
async def handle_voice_endpoint(
    response: Response,
    audio: UploadFile = File(...),
    language: Literal["tr", "en"] | None = Form(default=VOICE_LANGUAGE),
    current_date: str | None = Form(default=None),
    timezone: str | None = Form(default=None),
    require_confirmation: bool = Form(default=False),
    conversation_id: str | None = Form(default=None),
    accept: str | None = Header(default=None),
    user: AuthenticatedUser = Depends(current_user),
    store: PlanStore = Depends(get_plan_store),
    stt_client: GroqWhisperClient = Depends(get_stt_client),
    llm_client: NebiusLLMClient = Depends(get_llm_client),
    tts_client: GroqTTSClient = Depends(get_tts_client),
    engine: ConversationEngine = Depends(get_conversation_engine),
) -> Response | VoicePlanResponse | VoiceClarifyResponse:

    try:
        # 1. Timezone verification (D-010)
        if timezone is not None and timezone != user.timezone:
            raise APIError(
                422,
                "validation_error",
                f"Provided timezone '{timezone}' does not match registered user timezone '{user.timezone}'.",
            )

        try:
            user_zone = ZoneInfo(user.timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise APIError(422, "validation_error", f"Invalid user timezone: {user.timezone}") from exc

        # 2. Date verification / default to today in user's timezone
        if current_date is not None:
            try:
                date.fromisoformat(current_date)
                resolved_date = current_date
            except ValueError as exc:
                raise APIError(422, "validation_error", f"Invalid calendar date: {current_date}") from exc
        else:
            resolved_date = datetime.now(user_zone).date().isoformat()

        # 3. Stream-based audio reading with size limit (KK-3: <=320 KB / 413 payload_too_large)
        audio_bytes = await _read_audio_stream_with_limit(audio, max_bytes=MAX_AUDIO_BYTES)

        # 4. Strict validation / raw PCM conversion / safe WAV repair
        if _is_declared_raw_pcm(audio.content_type, audio.filename):
            if audio_bytes.startswith(b"RIFF"):
                try:
                    audio_bytes = stt_client.validate_wav_audio(audio_bytes, max_seconds=10.0)
                except STTValidationError as exc:
                    raise APIError(422, "validation_error", str(exc)) from exc
            else:
                try:
                    audio_bytes = pcm_to_wav(audio_bytes, max_seconds=10.0)
                except STTValidationError as exc:
                    raise APIError(422, "validation_error", str(exc)) from exc
        else:
            try:
                audio_bytes = stt_client.validate_wav_audio(audio_bytes, max_seconds=10.0)
            except STTValidationError as exc:
                raise APIError(422, "validation_error", str(exc)) from exc

        # 5. Speech-to-text conversion (B5-1) - strictly locked to English for ESP32 voice flow
        try:
            transcript = stt_client.transcribe(
                audio_bytes,
                language=VOICE_LANGUAGE,
                validate_audio=False,  # Already strictly validated above
            )
        except STTValidationError as exc:
            raise APIError(422, "validation_error", str(exc)) from exc
        except STTTimeoutError as exc:
            logger.warning("STT service timed out: %s", exc)
            raise APIError(503, "llm_unavailable", "Speech-to-text request timed out.") from exc
        except STTUnavailableError as exc:
            logger.warning("STT service unavailable: %s", exc)
            raise APIError(503, "llm_unavailable", "Speech-to-text service is unavailable.") from exc
        except STTResponseError as exc:
            logger.warning("STT service error HTTP %s: %s", exc.status_code, exc.message)
            raise APIError(503, "llm_unavailable", "Speech-to-text service returned an error.") from exc
        except STTConfigurationError as exc:
            logger.error("STT service configuration error: %s", exc)
            raise APIError(503, "llm_unavailable", "Speech-to-text service configuration error.") from exc
        except STTParseError as exc:
            logger.warning("STT parse error: %s", exc)
            raise APIError(502, "parse_failed", "Speech-to-text response could not be parsed.") from exc
        except STTError as exc:
            logger.warning("STT unexpected error: %s", exc)
            raise APIError(503, "llm_unavailable", "Speech-to-text service failed.") from exc

        if not transcript or not transcript.strip():
            raise APIError(422, "validation_error", "Audio transcription produced no intelligible text.")

        # Natural language text parsing (strictly locked to English for ESP32 voice flow)
        parsed_plan = parse_text(
            text=transcript,
            current_date=resolved_date,
            timezone=user.timezone,
            language=VOICE_LANGUAGE,
            llm_client=llm_client,
        )

        active_session = engine.get_active_session_for_user(user.id)
        if _wants_wav(accept) or require_confirmation or active_session is not None or conversation_id:
            turn_result = engine.process_message(
                user=user,
                text=transcript,
                conversation_id=conversation_id or (active_session.id if active_session else None),
                current_date=resolved_date,
                timezone_name=user.timezone,
                store=store,
                llm_client=llm_client,
                parsed_plan=parsed_plan,
                source="voice",
            )
            spoken_text = turn_result.reply_text

            if turn_result.state == ConversationState.AWAITING_CONFIRMATION:
                prop_record = turn_result.proposal or {}
                prop_title = str(prop_record.get("title") or "Plan").strip()
                proposal_id = str(prop_record.get("id") or "")
                if _wants_wav(accept) and get_settings().tts_enabled:
                    try:
                        wav_bytes = tts_client.synthesize(spoken_text)
                        headers = {
                            "Content-Type": "audio/wav",
                            "X-Transcript": _header_text(transcript),
                            "X-Reply-Text": _header_text(spoken_text),
                            "X-Intent": "propose_plan",
                            "X-Proposal-Id": proposal_id,
                            "X-Proposal-Title": _header_text(prop_title),
                            "X-Needs-Button": "true",
                            "X-Conversation-Id": str(turn_result.conversation_id),
                        }
                        return Response(
                            content=wav_bytes,
                            status_code=status.HTTP_201_CREATED,
                            media_type="audio/wav",
                            headers=headers,
                        )
                    except TTSError as exc:
                        logger.warning("TTS failed on propose_plan, falling back to JSON: %s", exc)

                response.status_code = status.HTTP_201_CREATED
                return VoicePlanResponse(
                    transcript=transcript,
                    parsed_plan=ParsedPlan({
                        "intent": "create_plan",
                        "title": prop_title,
                        "category": prop_record.get("category", "other"),
                        "date": prop_record.get("planned_start", "")[:10] or resolved_date,
                        "time": prop_record.get("planned_start", "")[11:16] or "18:00",
                        "duration_minutes": prop_record.get("duration_minutes", 60),
                        "recurrence": prop_record.get("recurrence_rule"),
                        "language": "en",
                        "needs_weather_check": False,
                        "clarification_question": None,
                        "confidence": 0.95,
                    }),
                    proposal=ProposalResponse.model_validate(prop_record) if prop_record else None,
                    plan=None,
                    spoken_recommendation=spoken_text,
                )

            if turn_result.state == ConversationState.COMPLETED:
                if _wants_wav(accept) and get_settings().tts_enabled:
                    try:
                        wav_bytes = tts_client.synthesize(spoken_text)
                        headers = {
                            "Content-Type": "audio/wav",
                            "X-Transcript": _header_text(transcript),
                            "X-Reply-Text": _header_text(spoken_text),
                            "X-Intent": "plan_confirmed",
                            "X-Needs-Button": "false",
                            "X-Conversation-Id": str(turn_result.conversation_id),
                        }
                        if turn_result.plan:
                            headers["X-Plan-Id"] = str(turn_result.plan.get("id"))
                        return Response(
                            content=wav_bytes,
                            status_code=status.HTTP_201_CREATED,
                            media_type="audio/wav",
                            headers=headers,
                        )
                    except TTSError as exc:
                        logger.warning("TTS failed on plan_confirmed, falling back to JSON: %s", exc)

                response.status_code = status.HTTP_201_CREATED
                return VoicePlanResponse(
                    transcript=transcript,
                    parsed_plan=ParsedPlan({
                        "intent": "create_plan",
                        "title": turn_result.plan.get("title", "Plan") if turn_result.plan else "Plan",
                        "category": turn_result.plan.get("category", "other") if turn_result.plan else "other",
                        "date": turn_result.plan.get("planned_start", "")[:10] if turn_result.plan else resolved_date,
                        "time": turn_result.plan.get("planned_start", "")[11:16] if turn_result.plan else "18:00",
                        "duration_minutes": 60,
                        "recurrence": None,
                        "language": "en",
                        "needs_weather_check": False,
                        "clarification_question": None,
                        "confidence": 0.95,
                    }),
                    plan=PlanResponse.model_validate(turn_result.plan) if turn_result.plan else None,
                    spoken_recommendation=spoken_text,
                )

            if turn_result.state == ConversationState.CANCELLED:
                if _wants_wav(accept) and get_settings().tts_enabled:
                    try:
                        wav_bytes = tts_client.synthesize(spoken_text)
                        headers = {
                            "Content-Type": "audio/wav",
                            "X-Transcript": _header_text(transcript),
                            "X-Reply-Text": _header_text(spoken_text),
                            "X-Intent": "plan_cancelled",
                            "X-Needs-Button": "false",
                            "X-Conversation-Id": str(turn_result.conversation_id),
                        }
                        return Response(
                            content=wav_bytes,
                            status_code=status.HTTP_200_OK,
                            media_type="audio/wav",
                            headers=headers,
                        )
                    except TTSError as exc:
                        logger.warning("TTS failed on plan_cancelled: %s", exc)

                response.status_code = status.HTTP_200_OK
                return VoiceClarifyResponse(
                    transcript=transcript,
                    parsed_plan=ParsedPlan({
                        "intent": "unsupported",
                        "title": None,
                        "category": None,
                        "date": None,
                        "time": None,
                        "duration_minutes": None,
                        "recurrence": None,
                        "language": "en",
                        "needs_weather_check": False,
                        "clarification_question": None,
                        "confidence": 0.95,
                    }),
                )

            if turn_result.state in (ConversationState.AWAITING_CLARIFICATION, ConversationState.COLLECTING_DETAILS):
                clarify_q = turn_result.reply_text
                if _wants_wav(accept) and get_settings().tts_enabled:
                    try:
                        wav_bytes = tts_client.synthesize(clarify_q)
                        headers = {
                            "Content-Type": "audio/wav",
                            "X-Transcript": _header_text(transcript),
                            "X-Reply-Text": _header_text(clarify_q),
                            "X-Intent": "clarify",
                            "X-Needs-Button": "false",
                            "X-Conversation-Id": str(turn_result.conversation_id),
                        }
                        return Response(
                            content=wav_bytes,
                            status_code=status.HTTP_200_OK,
                            media_type="audio/wav",
                            headers=headers,
                        )
                    except TTSError as exc:
                        logger.warning("TTS failed on clarify, falling back to JSON: %s", exc)

                response.status_code = status.HTTP_200_OK
                return VoiceClarifyResponse(
                    transcript=transcript,
                    parsed_plan=ParsedPlan({
                        "intent": "clarify",
                        "title": turn_result.pending_plan.get("title") if turn_result.pending_plan else "Plan",
                        "category": turn_result.pending_plan.get("category") if turn_result.pending_plan else "other",
                        "date": turn_result.pending_plan.get("date") if turn_result.pending_plan else None,
                        "time": turn_result.pending_plan.get("time") if turn_result.pending_plan else None,
                        "duration_minutes": turn_result.pending_plan.get("duration_minutes") if turn_result.pending_plan else None,
                        "recurrence": None,
                        "language": "en",
                        "needs_weather_check": False,
                        "clarification_question": clarify_q,
                        "confidence": 0.85,
                    }),
                )

            # UNSUPPORTED
            if _wants_wav(accept) and get_settings().tts_enabled:
                unsupported_msg = spoken_text or "Sorry, I could not understand that plan request."
                try:
                    wav_bytes = tts_client.synthesize(unsupported_msg)
                    headers = {
                        "Content-Type": "audio/wav",
                        "X-Transcript": _header_text(transcript),
                        "X-Reply-Text": _header_text(unsupported_msg),
                        "X-Intent": "unsupported",
                        "X-Needs-Button": "false",
                    }
                    return Response(
                        content=wav_bytes,
                        status_code=status.HTTP_200_OK,
                        media_type="audio/wav",
                        headers=headers,
                    )
                except TTSError as exc:
                    logger.warning("TTS failed on unsupported, falling back to JSON: %s", exc)

            response.status_code = status.HTTP_200_OK
            return VoiceClarifyResponse(
                transcript=transcript,
                parsed_plan=ParsedPlan({
                    "intent": "unsupported",
                    "title": None,
                    "category": None,
                    "date": None,
                    "time": None,
                    "duration_minutes": None,
                    "recurrence": None,
                    "language": "en",
                    "needs_weather_check": False,
                    "clarification_question": None,
                    "confidence": 0.7,
                }),
            )

        # 6. Legacy fallback for direct JSON requests where require_confirmation is False
        intent = parsed_plan.root.get("intent")

        # 7. Intent routing: create_plan
        if intent == "create_plan":
            plan_record = _build_plan_record(parsed_plan, user)
            is_proposal_mode = _wants_wav(accept) or require_confirmation

            if is_proposal_mode:
                proposal_record = store.create_plan_proposal(user_id=user.id, proposal=plan_record)
                prop_title = str(proposal_record.get("title") or "Plan").strip()
                prop_start = str(proposal_record.get("planned_start") or "")
                time_part = prop_start[11:16]
                date_part = prop_start[:10]
                spoken_text = f"Drafted {prop_title} on {date_part} at {time_part}. Press button 1 to accept or button 2 to cancel."

                if _wants_wav(accept) and get_settings().tts_enabled:
                    try:
                        wav_bytes = tts_client.synthesize(spoken_text)
                        headers = {
                            "Content-Type": "audio/wav",
                            "X-Transcript": _header_text(transcript),
                            "X-Reply-Text": _header_text(spoken_text),
                            "X-Intent": "propose_plan",
                            "X-Proposal-Id": str(proposal_record["id"]),
                            "X-Proposal-Title": _header_text(prop_title),
                            "X-Needs-Button": "true",
                        }
                        return Response(
                            content=wav_bytes,
                            status_code=status.HTTP_201_CREATED,
                            media_type="audio/wav",
                            headers=headers,
                        )
                    except TTSError as exc:
                        logger.warning("TTS failed on propose_plan, falling back to JSON: %s", exc)

                response.status_code = status.HTTP_201_CREATED
                return VoicePlanResponse(
                    transcript=transcript,
                    parsed_plan=parsed_plan,
                    proposal=ProposalResponse.model_validate(proposal_record),
                    plan=None,
                    spoken_recommendation=spoken_text,
                )

            # Direct plan creation fallback (legacy JSON requests where require_confirmation is False)
            created_plan_dict = store.create_plan(plan_record)
            try:
                recommendation = get_suggestion_for_plan(
                    plan_id=str(created_plan_dict["id"]),
                    user=user,
                    store=store,
                    llm=llm_client,
                )["suggestion"]
            except Exception:
                logger.exception("Could not retrieve recommendation for newly created voice plan")
                recommendation = None
            spoken_text = recommendation["message"] if recommendation else None
            if spoken_text and (len(spoken_text) > 240 or "\n" in spoken_text or "\r" in spoken_text):
                logger.warning("Saved recommendation is not suitable for spoken playback")
                spoken_text = None
            if not spoken_text:
                plan_title = str(created_plan_dict.get("title") or "Plan").strip()
                spoken_text = f"Plan '{plan_title}' has been scheduled."

            response.status_code = status.HTTP_201_CREATED
            return VoicePlanResponse(
                transcript=transcript,
                parsed_plan=parsed_plan,
                plan=PlanResponse.model_validate(created_plan_dict),
                spoken_recommendation=spoken_text,
            )

        # 8. Clarify -> do NOT persist + 200 OK
        if intent == "clarify":
            clarify_question = parsed_plan.root.get("clarification_question") or "Please specify the date or time for this plan."
            if _wants_wav(accept) and get_settings().tts_enabled:
                try:
                    wav_bytes = tts_client.synthesize(clarify_question)
                    headers = {
                        "Content-Type": "audio/wav",
                        "X-Transcript": _header_text(transcript),
                        "X-Reply-Text": _header_text(clarify_question),
                        "X-Intent": "clarify",
                        "X-Needs-Button": "false",
                    }
                    return Response(
                        content=wav_bytes,
                        status_code=status.HTTP_200_OK,
                        media_type="audio/wav",
                        headers=headers,
                    )
                except TTSError as exc:
                    logger.warning("TTS failed on clarify, falling back to JSON: %s", exc)

            response.status_code = status.HTTP_200_OK
            return VoiceClarifyResponse(
                transcript=transcript,
                parsed_plan=parsed_plan,
            )

        # 9. Unsupported / other -> do NOT persist + 200 OK
        if _wants_wav(accept) and get_settings().tts_enabled:
            unsupported_msg = "Sorry, I could not understand that plan request."
            try:
                wav_bytes = tts_client.synthesize(unsupported_msg)
                headers = {
                    "Content-Type": "audio/wav",
                    "X-Transcript": _header_text(transcript),
                    "X-Reply-Text": _header_text(unsupported_msg),
                    "X-Intent": "unsupported",
                    "X-Needs-Button": "false",
                }
                return Response(
                    content=wav_bytes,
                    status_code=status.HTTP_200_OK,
                    media_type="audio/wav",
                    headers=headers,
                )
            except TTSError as exc:
                logger.warning("TTS failed on unsupported, falling back to JSON: %s", exc)

        response.status_code = status.HTTP_200_OK
        return VoiceClarifyResponse(
            transcript=transcript,
            parsed_plan=parsed_plan,
        )

    finally:
        await audio.close()
