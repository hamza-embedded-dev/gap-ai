from __future__ import annotations

from datetime import date, datetime, time, timedelta
import logging
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile, status
from pydantic import BaseModel, ConfigDict

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
from app.api.errors import APIError
from app.api.parse import parse_text
from app.api.plans import PlanResponse, current_user
from app.db.plans import AuthenticatedUser, PlanStore, get_plan_store
from app.schemas.parsed_plan import ParsedPlan

logger = logging.getLogger(__name__)

router = APIRouter()

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
    model_config = ConfigDict(extra="forbid")

    transcript: str
    parsed_plan: ParsedPlan
    plan: PlanResponse


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


@router.post(
    "/voice",
    response_model=VoicePlanResponse | VoiceClarifyResponse,
    status_code=status.HTTP_201_CREATED,
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
) -> VoicePlanResponse | VoiceClarifyResponse:
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

        # 5. Speech-to-text conversion (B5-1)
        try:
            transcript = stt_client.transcribe(
                audio_bytes,
                language=language,
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

        # 6. Natural language text parsing (B2-2)
        parsed_plan = parse_text(
            text=transcript,
            current_date=resolved_date,
            timezone=user.timezone,
            language=language,
            llm_client=llm_client,
        )

        intent = parsed_plan.root.get("intent")

        # 7. Intent routing: create_plan -> persist plan (K-3 source: "voice") + 201 Created
        if intent == "create_plan":
            plan_record = _build_plan_record(parsed_plan, user)
            created_plan_dict = store.create_plan(plan_record)
            response.status_code = status.HTTP_201_CREATED
            return VoicePlanResponse(
                transcript=transcript,
                parsed_plan=parsed_plan,
                plan=PlanResponse.model_validate(created_plan_dict),
            )

        # 8. Clarify / Unsupported -> do NOT persist + 200 OK
        response.status_code = status.HTTP_200_OK
        return VoiceClarifyResponse(
            transcript=transcript,
            parsed_plan=parsed_plan,
        )
    finally:
        await audio.close()
