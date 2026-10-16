from __future__ import annotations

from datetime import date
from functools import lru_cache
import logging
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.ai.llm import (
    LLMConfigurationError,
    LLMParseError,
    LLMResponseError,
    LLMUnavailableError,
    NebiusLLMClient,
    get_llm_client,
)
from app.api.errors import APIError
from app.api.plans import current_user
from app.db.plans import AuthenticatedUser
from app.schemas.parsed_plan import ParsedPlan

logger = logging.getLogger(__name__)

router = APIRouter()

PROMPT_PATH = Path(__file__).resolve().parents[3] / "ai" / "prompts" / "parse_plan.md"


@lru_cache(maxsize=1)
def _load_system_prompt() -> str:
    if not PROMPT_PATH.is_file():
        raise RuntimeError(f"System prompt file not found at {PROMPT_PATH}")
    return PROMPT_PATH.read_text(encoding="utf-8")


class ParseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1)
    current_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    language: Literal["tr", "en"] | None = None
    timezone: str | None = None

    @field_validator("current_date")
    @classmethod
    def validate_date(cls, v: str) -> str:
        try:
            date.fromisoformat(v)
        except ValueError as exc:
            raise ValueError(f"Invalid calendar date: {v}") from exc
        return v


def _build_prompt_messages(
    text: str,
    current_date: str,
    timezone: str,
    language: str | None,
) -> list[dict[str, str]]:
    system_prompt = _load_system_prompt()
    user_content = (
        f"Context:\n"
        f"- Current Date: {current_date}\n"
        f"- Timezone: {timezone}\n"
        f"- Requested Language: {language if language else 'auto-detect'}\n\n"
        f"User Input:\n{text}\n\n"
        f"Output the ParsedPlan JSON object:"
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]


def _build_retry_messages(
    text: str,
    current_date: str,
    timezone: str,
    language: str | None,
) -> list[dict[str, str]]:
    system_prompt = _load_system_prompt()
    user_content = (
        f"Context:\n"
        f"- Current Date: {current_date}\n"
        f"- Timezone: {timezone}\n"
        f"- Requested Language: {language if language else 'auto-detect'}\n\n"
        f"User Input:\n{text}\n\n"
        f"IMPORTANT: The previous output failed schema validation. "
        f"You MUST output ONLY a valid JSON object conforming strictly to the ParsedPlan schema in ai/schema.json. "
        f"Include all 11 required keys."
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]


def parse_text(
    text: str,
    *,
    current_date: str | date,
    timezone: str,
    language: str | None = None,
    llm_client: NebiusLLMClient | None = None,
) -> ParsedPlan:
    """Parse natural language text into a validated ParsedPlan without persisting.

    Reusable across HTTP API (POST /parse) and B5 voice pipeline.
    """
    if not text or not text.strip():
        raise APIError(422, "validation_error", "Text cannot be empty.")

    if isinstance(current_date, date):
        formatted_date = current_date.isoformat()
    else:
        formatted_date = str(current_date).strip()
        try:
            date.fromisoformat(formatted_date)
        except ValueError as exc:
            raise APIError(422, "validation_error", f"Invalid calendar date: {current_date}") from exc

    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise APIError(422, "validation_error", f"Invalid timezone: {timezone}") from exc

    client = llm_client if llm_client is not None else get_llm_client()

    messages = _build_prompt_messages(
        text=text,
        current_date=formatted_date,
        timezone=timezone,
        language=language,
    )

    for attempt in range(2):
        current_messages = (
            messages
            if attempt == 0
            else _build_retry_messages(
                text=text,
                current_date=formatted_date,
                timezone=timezone,
                language=language,
            )
        )
        try:
            raw_response = client.complete_json(current_messages)
            if not isinstance(raw_response, dict):
                raise LLMParseError("Model output is not a JSON object")
            return ParsedPlan.model_validate(raw_response)
        except LLMUnavailableError as exc:
            logger.warning("LLM provider unavailable")
            raise APIError(503, "llm_unavailable", "Model provider is unavailable.") from exc
        except LLMResponseError as exc:
            logger.warning("LLM provider returned error")
            raise APIError(503, "llm_unavailable", "Model provider returned an error.") from exc
        except LLMConfigurationError as exc:
            logger.error("LLM client configuration error")
            raise APIError(503, "llm_unavailable", "LLM service configuration error.") from exc
        except (LLMParseError, ValidationError, ValueError) as exc:
            logger.warning("Parse attempt %d produced invalid schema output", attempt + 1)
            if attempt == 0:
                continue
            raise APIError(
                502,
                "parse_failed",
                "Model output does not conform to the schema after retry.",
            ) from exc

    raise APIError(502, "parse_failed", "Failed to parse text into a valid plan.")


@router.post("/parse", response_model=ParsedPlan, status_code=200)
def parse_endpoint(
    payload: ParseRequest,
    user: AuthenticatedUser = Depends(current_user),
    llm_client: NebiusLLMClient = Depends(get_llm_client),
) -> ParsedPlan:
    if payload.timezone is not None and payload.timezone != user.timezone:
        raise APIError(
            422,
            "validation_error",
            f"Provided timezone '{payload.timezone}' does not match registered user timezone '{user.timezone}'.",
        )

    return parse_text(
        text=payload.text,
        current_date=payload.current_date,
        timezone=user.timezone,
        language=payload.language,
        llm_client=llm_client,
    )
