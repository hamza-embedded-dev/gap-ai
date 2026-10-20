from __future__ import annotations

from datetime import date, datetime, time, timedelta
import logging
from typing import Literal
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, File, Form, Header, Response, UploadFile, status
from pydantic import BaseModel, ConfigDict

from app.ai.llm import NebiusLLMClient, get_llm_client
from app.ai.reply import build_reply_text
from app.ai.stt import (
    GroqWhisperClient,
    STTConfigurationError,
    STTError,
    STTParseError,
    STTResponseError,
    STTUnavailableError,
    STTValidationError,
    get_stt_client,
)
from app.ai.tts import GroqTTSClient, TTSError, get_tts_client
from app.api.errors import APIError
from app.api.parse import parse_text
from app.api.plans import PlanResponse, current_user
from app.config import get_settings
from app.db.plans import AuthenticatedUser, PlanStore, get_plan_store
from app.schemas.parsed_plan import ParsedPlan

logger = logging.getLogger(__name__)

router = APIRouter()

# 320 KB in binary bytes (320 * 1024 = 327,680 bytes)
# Provides headroom for standard WAV header while enforcing 10s audio limit.
MAX_AUDIO_BYTES: int = 320 * 1024
STREAM_CHUNK_SIZE: int = 64 * 1024


class VoicePlanResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transcript: str
    parsed_plan: ParsedPlan
    plan: PlanResponse
    reply_text: str


class VoiceClarifyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transcript: str
    parsed_plan: ParsedPlan
    reply_text: str


def _wants_wav(accept: str | None) -> bool:
    return bool(accept) and "audio/wav" in accept.lower()


def _header_text(value: str) -> str:
    # HTTP headers are latin-1; URL-encode so Turkish characters survive intact.
    return quote(value, safe="")


def _spoken_reply(
    *,
    accept: str | None,
    tts_client: GroqTTSClient,
    status_code: int,
    transcript: str,
    reply_text: str,
    intent: str,
    plan_id: str | None,
) -> Response | None:
    """Returns the reply as audio/wav when the client asked for it and TTS works, else None.

    TTS is optional (api-contract): any TTS failure falls back to the JSON response.
    """
    if not _wants_wav(accept) or not get_settings().tts_enabled:
        return None
    try:
        audio = tts_client.synthesize(reply_text)
    except TTSError as exc:
        logger.warning("TTS failed, falling back to JSON reply: %s", exc)
        return None

    headers = {
        "X-Transcript": _header_text(transcript),
        "X-Reply-Text": _header_text(reply_text),
        "X-Intent": intent,
    }
    if plan_id:
        headers["X-Plan-Id"] = plan_id
    return Response(content=audio, media_type="audio/wav", status_code=status_code, headers=headers)


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


@router.post(
    "/voice",
    response_model=VoicePlanResponse | VoiceClarifyResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        200: {"content": {"audio/wav": {}}},
        201: {"content": {"audio/wav": {}}},
    },
)
async def handle_voice_endpoint(
    response: Response,
    audio: UploadFile = File(...),
    language: Literal["tr", "en"] | None = Form(default=None),
    current_date: str | None = Form(default=None),
    timezone: str | None = Form(default=None),
    user: AuthenticatedUser = Depends(current_user),
    store: PlanStore = Depends(get_plan_store),
    stt_client: GroqWhisperClient = Depends(get_stt_client),
    llm_client: NebiusLLMClient = Depends(get_llm_client),
    tts_client: GroqTTSClient = Depends(get_tts_client),
    accept: str | None = Header(default=None),
) -> VoicePlanResponse | VoiceClarifyResponse | Response:
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

    # 4. Strict WAV validation (mono, 16 kHz, 16-bit PCM, <=10s)
    try:
        stt_client.validate_wav_audio(audio_bytes, max_seconds=10.0)
    except STTValidationError as exc:
        raise APIError(422, "validation_error", str(exc)) from exc

    # 5. Speech-to-text conversion (B5-1)
    try:
        transcript = stt_client.transcribe(
            audio_bytes,
            language=language,
            validate_audio=False,  # Already strictly validated above
        )
    except STTValidationError as exc:
        raise APIError(422, "validation_error", str(exc)) from exc
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

    # 6. Natural language text parsing (B2-2)
    parsed_plan = parse_text(
        text=transcript,
        current_date=resolved_date,
        timezone=user.timezone,
        language=language,
        llm_client=llm_client,
    )

    intent = str(parsed_plan.root.get("intent"))
    reply_text = build_reply_text(parsed_plan.root, today=resolved_date)

    # 7. Intent routing: create_plan -> persist plan (K-3 source: "voice") + 201 Created
    if intent == "create_plan":
        plan_record = _build_plan_record(parsed_plan, user)
        created_plan_dict = store.create_plan(plan_record)
        plan = PlanResponse.model_validate(created_plan_dict)
        spoken = _spoken_reply(
            accept=accept,
            tts_client=tts_client,
            status_code=status.HTTP_201_CREATED,
            transcript=transcript,
            reply_text=reply_text,
            intent=intent,
            plan_id=str(created_plan_dict.get("id") or "") or None,
        )
        if spoken is not None:
            return spoken
        response.status_code = status.HTTP_201_CREATED
        return VoicePlanResponse(
            transcript=transcript,
            parsed_plan=parsed_plan,
            plan=plan,
            reply_text=reply_text,
        )

    # 8. Clarify / Unsupported -> do NOT persist + 200 OK
    spoken = _spoken_reply(
        accept=accept,
        tts_client=tts_client,
        status_code=status.HTTP_200_OK,
        transcript=transcript,
        reply_text=reply_text,
        intent=intent,
        plan_id=None,
    )
    if spoken is not None:
        return spoken
    response.status_code = status.HTTP_200_OK
    return VoiceClarifyResponse(
        transcript=transcript,
        parsed_plan=parsed_plan,
        reply_text=reply_text,
    )
