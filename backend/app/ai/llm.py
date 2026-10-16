from __future__ import annotations

import json
import logging
from typing import Any, Mapping
from urllib.parse import urljoin

import httpx
from pydantic import SecretStr

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Exception Hierarchy
# -----------------------------------------------------------------------------


class LLMError(Exception):
    """Base exception for all LLM client errors."""


class LLMConfigurationError(LLMError):
    """Raised when the LLM client is misconfigured (e.g. missing API key)."""


class LLMUnavailableError(LLMError):
    """Raised when the LLM provider cannot be reached (timeout, connect error, 5xx).

    Corresponds to contract HTTP 503 llm_unavailable at the API layer.
    """


class LLMResponseError(LLMError):
    """Raised when the provider returns a non-2xx client error (e.g. HTTP 400, 401, 429)."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(f"Provider returned HTTP {status_code}: {message}")
        self.status_code = status_code
        self.message = message


class LLMParseError(LLMError):
    """Raised when the LLM output is not valid JSON or lacks the expected shape.

    Corresponds to contract HTTP 502 parse_failed at the API layer.
    """


# -----------------------------------------------------------------------------
# Nebius Token Factory LLM Client
# -----------------------------------------------------------------------------


class NebiusLLMClient:
    """Synchronous HTTP client for NVIDIA Nemotron models hosted on Nebius Token Factory.

    Uses an OpenAI-compatible /chat/completions endpoint over httpx.Client.
    Keeps API keys strictly in SecretStr and never leaks secrets in exceptions or logs.
    """

    def __init__(
        self,
        api_key: str | SecretStr | None = None,
        base_url: str | None = None,
        default_model: str | None = None,
        default_timeout: float | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        settings: Settings = get_settings()

        resolved_key = api_key if api_key is not None else settings.nebius_api_key
        if isinstance(resolved_key, str):
            self._api_key = SecretStr(resolved_key) if resolved_key else None
        else:
            self._api_key = resolved_key

        self._base_url = (
            base_url
            if base_url is not None
            else settings.nebius_base_url or "https://api.tokenfactory.nebius.com/v1"
        ).rstrip("/") + "/"

        self._default_model = (
            default_model
            if default_model is not None
            else settings.nebius_model or "nvidia/Llama-3.1-Nemotron-70B-Instruct-HF"
        )

        self._default_timeout = (
            default_timeout
            if default_timeout is not None
            else settings.nebius_timeout_seconds or 30.0
        )

        self._external_client = http_client is not None
        self._client = http_client or httpx.Client(timeout=self._default_timeout)

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def default_model(self) -> str:
        return self._default_model

    @property
    def default_timeout(self) -> float:
        return self._default_timeout

    def _get_api_key_value(self) -> str:
        if not self._api_key or not self._api_key.get_secret_value().strip():
            raise LLMConfigurationError(
                "NEBIUS_API_KEY is missing or empty. Please configure it in your environment."
            )
        return self._api_key.get_secret_value().strip()

    def _build_headers(self) -> dict[str, str]:
        key = self._get_api_key_value()
        return {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _chat_completions_url(self) -> str:
        base = self._base_url.rstrip("/")
        if not base.endswith("/v1"):
            base = f"{base}/v1"
        return f"{base}/chat/completions"

    def _sanitize_error_message(self, text: str) -> str:
        """Strip raw API key if it somehow appears in upstream error text."""
        if self._api_key:
            raw_key = self._api_key.get_secret_value()
            if raw_key and len(raw_key) > 4 and raw_key in text:
                text = text.replace(raw_key, "[REDACTED_API_KEY]")
        return text

    def call(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        json_mode: bool = False,
        temperature: float = 0.0,
        timeout: float | None = None,
        extra_payload: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Low-level synchronous call to Nebius Token Factory /chat/completions.

        Returns the raw parsed JSON response dictionary from the provider.
        """
        url = self._chat_completions_url()
        headers = self._build_headers()
        selected_model = model or self._default_model

        prepared_messages = [dict(m) for m in messages]
        payload: dict[str, Any] = {
            "model": selected_model,
            "messages": prepared_messages,
            "temperature": temperature,
        }

        if json_mode:
            payload["response_format"] = {"type": "json_object"}
            has_json_instruction = any(
                "json" in str(m.get("content", "")).lower() for m in prepared_messages
            )
            if not has_json_instruction:
                # OpenAI-compatible JSON mode specification requires the word 'json' in messages.
                # Inject a system directive to guarantee compliance and structured output.
                prepared_messages.insert(
                    0,
                    {
                        "role": "system",
                        "content": "You are a helpful assistant. Output valid JSON.",
                    },
                )

        if extra_payload:
            payload.update(extra_payload)

        call_timeout = timeout if timeout is not None else self._default_timeout

        try:
            response = self._client.post(
                url,
                json=payload,
                headers=headers,
                timeout=call_timeout,
            )
        except (httpx.TimeoutException, TimeoutError) as exc:
            logger.warning("Nebius LLM call timed out after %s seconds", call_timeout)
            raise LLMUnavailableError(
                f"LLM request timed out after {call_timeout}s"
            ) from exc
        except (httpx.ConnectError, httpx.NetworkError) as exc:
            logger.warning("Nebius LLM network connection error")
            raise LLMUnavailableError(
                "Failed to connect to Nebius LLM provider"
            ) from exc
        except httpx.HTTPError as exc:
            logger.warning("Nebius LLM HTTP transport error: %s", type(exc).__name__)
            raise LLMUnavailableError(
                f"Nebius LLM transport error: {type(exc).__name__}"
            ) from exc

        if response.status_code >= 500:
            sanitized = self._sanitize_error_message(response.text)[:300]
            logger.error("Nebius LLM returned server error %d: %s", response.status_code, sanitized)
            raise LLMUnavailableError(
                f"Nebius LLM provider returned server error HTTP {response.status_code}"
            )

        if response.status_code >= 400:
            sanitized = self._sanitize_error_message(response.text)[:300]
            logger.error("Nebius LLM returned client error %d: %s", response.status_code, sanitized)
            raise LLMResponseError(
                status_code=response.status_code,
                message=sanitized,
            )

        try:
            data = response.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise LLMParseError("Nebius LLM response body is not valid JSON") from exc

        if not isinstance(data, dict):
            raise LLMParseError("Nebius LLM response body must be a JSON object")

        return data

    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float = 0.0,
        timeout: float | None = None,
    ) -> str:
        """Sends chat messages and returns the raw assistant message content as a string."""
        data = self.call(
            messages=messages,
            model=model,
            json_mode=False,
            temperature=temperature,
            timeout=timeout,
        )
        return self._extract_content(data)

    def complete_json(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float = 0.0,
        timeout: float | None = None,
    ) -> dict[str, Any] | list[Any]:
        """Calls Nebius Token Factory in JSON mode and parses the assistant output as JSON.

        Separation of concerns:
        This method verifies syntactic JSON validity and returns the parsed structure.
        Domain contract validation (e.g. against ai/schema.json / ParsedPlan) is
        intentionally delegated to the higher-level service/endpoint (B2-2 / parse_text).
        """
        data = self.call(
            messages=messages,
            model=model,
            json_mode=True,
            temperature=temperature,
            timeout=timeout,
        )
        content = self._extract_content(data)

        try:
            parsed = json.loads(content)
        except (json.JSONDecodeError, ValueError) as exc:
            raise LLMParseError(
                f"Model response in JSON mode is not valid JSON: {exc}"
            ) from exc

        return parsed

    def _extract_content(self, response_data: dict[str, Any]) -> str:
        choices = response_data.get("choices")
        if not choices or not isinstance(choices, list):
            raise LLMParseError("Nebius LLM response missing 'choices' list")

        first_choice = choices[0]
        if not isinstance(first_choice, dict):
            raise LLMParseError("Nebius LLM response 'choices[0]' must be an object")

        message = first_choice.get("message")
        if not isinstance(message, dict):
            raise LLMParseError("Nebius LLM response 'choices[0].message' must be an object")

        content = message.get("content")
        if content is None or not isinstance(content, str):
            raise LLMParseError("Nebius LLM response message content is null or not a string")

        return content

    def close(self) -> None:
        """Close the underlying httpx client if created internally."""
        if not self._external_client:
            self._client.close()

    def __enter__(self) -> "NebiusLLMClient":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()


def get_llm_client() -> NebiusLLMClient:
    """Dependency injection helper returning a configured NebiusLLMClient."""
    return NebiusLLMClient()
