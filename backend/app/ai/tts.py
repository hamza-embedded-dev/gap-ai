from __future__ import annotations

import logging
from typing import Any

import httpx
from pydantic import SecretStr

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

# Spoken replies are one or two sentences; cap the input so a bad upstream value
# can never turn into a long (slow, expensive) synthesis request.
MAX_TTS_INPUT_CHARS: int = 500


# -----------------------------------------------------------------------------
# Exception Hierarchy
# -----------------------------------------------------------------------------


class TTSError(Exception):
    """Base exception for all text-to-speech client errors."""


class TTSConfigurationError(TTSError):
    """Raised when the TTS client is misconfigured (e.g. missing GROQ_API_KEY)."""


class TTSValidationError(TTSError):
    """Raised when the text to synthesize is empty."""


class TTSUnavailableError(TTSError):
    """Raised when Groq cannot be reached (timeout, connect error, 5xx)."""


class TTSResponseError(TTSError):
    """Raised when Groq returns a non-2xx client error (e.g. HTTP 400, 401, 429)."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(f"Groq API returned HTTP {status_code}: {message}")
        self.status_code = status_code
        self.message = message


class TTSParseError(TTSError):
    """Raised when Groq returns a body that is not a WAV file."""


# -----------------------------------------------------------------------------
# Groq Text-to-Speech Client
# -----------------------------------------------------------------------------


class GroqTTSClient:
    """Synchronous HTTP client for Groq text-to-speech (OpenAI-compatible /audio/speech).

    Always requests WAV so the ESP32 can play PCM over I2S without a decoder.
    Keeps the API key in SecretStr and never leaks it in exceptions or logs.
    """

    def __init__(
        self,
        api_key: str | SecretStr | None = None,
        base_url: str | None = None,
        default_model: str | None = None,
        default_voice: str | None = None,
        default_timeout: float | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        settings: Settings = get_settings()

        resolved_key = api_key if api_key is not None else settings.groq_api_key
        if isinstance(resolved_key, str):
            self._api_key = SecretStr(resolved_key) if resolved_key else None
        else:
            self._api_key = resolved_key

        self._base_url = (
            base_url
            if base_url is not None
            else settings.groq_base_url or "https://api.groq.com/openai/v1"
        ).rstrip("/") + "/"

        self._default_model = default_model or settings.tts_model
        self._default_voice = default_voice or settings.tts_voice
        self._default_timeout = (
            default_timeout
            if default_timeout is not None
            else settings.tts_timeout_seconds or 10.0
        )

        self._external_client = http_client is not None
        self._client = http_client or httpx.Client(timeout=self._default_timeout)

    @property
    def default_model(self) -> str:
        return self._default_model

    @property
    def default_voice(self) -> str:
        return self._default_voice

    @property
    def default_timeout(self) -> float:
        return self._default_timeout

    def _get_api_key_value(self) -> str:
        if not self._api_key or not self._api_key.get_secret_value().strip():
            raise TTSConfigurationError(
                "GROQ_API_KEY is missing or empty. Please configure it in your environment."
            )
        return self._api_key.get_secret_value().strip()

    def _speech_url(self) -> str:
        base = self._base_url.rstrip("/")
        if not base.endswith("/audio/speech"):
            if not base.endswith("/v1"):
                base = f"{base}/v1"
            base = f"{base}/audio/speech"
        return base

    def _sanitize_error_message(self, text: str) -> str:
        """Strip raw API key if it somehow appears in upstream error text."""
        if self._api_key:
            raw_key = self._api_key.get_secret_value()
            if raw_key and len(raw_key) > 4 and raw_key in text:
                text = text.replace(raw_key, "[REDACTED_API_KEY]")
        return text

    def synthesize(
        self,
        text: str,
        *,
        model: str | None = None,
        voice: str | None = None,
        timeout: float | None = None,
    ) -> bytes:
        """Converts text to speech and returns the WAV file bytes."""
        cleaned = (text or "").strip()
        if not cleaned:
            raise TTSValidationError("Text to synthesize is empty.")
        cleaned = cleaned[:MAX_TTS_INPUT_CHARS]

        headers = {
            "Authorization": f"Bearer {self._get_api_key_value()}",
            "Content-Type": "application/json",
            "Accept": "audio/wav",
        }
        payload: dict[str, Any] = {
            "model": model or self._default_model,
            "input": cleaned,
            "voice": voice or self._default_voice,
            "response_format": "wav",
        }
        call_timeout = timeout if timeout is not None else self._default_timeout

        try:
            response = self._client.post(
                self._speech_url(),
                json=payload,
                headers=headers,
                timeout=call_timeout,
            )
        except (httpx.TimeoutException, TimeoutError) as exc:
            logger.warning("Groq TTS call timed out after %s seconds", call_timeout)
            raise TTSUnavailableError(f"TTS request timed out after {call_timeout}s") from exc
        except (httpx.ConnectError, httpx.NetworkError) as exc:
            logger.warning("Groq TTS network connection error")
            raise TTSUnavailableError("Failed to connect to Groq TTS provider") from exc
        except httpx.HTTPError as exc:
            logger.warning("Groq TTS HTTP transport error: %s", type(exc).__name__)
            raise TTSUnavailableError(
                f"Groq TTS transport error: {type(exc).__name__}"
            ) from exc

        if response.status_code >= 500:
            sanitized = self._sanitize_error_message(response.text[:300])
            logger.error("Groq TTS returned server error %d: %s", response.status_code, sanitized)
            raise TTSUnavailableError(
                f"Groq TTS provider returned server error HTTP {response.status_code}"
            )

        if response.status_code >= 400:
            sanitized = self._sanitize_error_message(response.text[:300])
            logger.error("Groq TTS returned client error %d: %s", response.status_code, sanitized)
            raise TTSResponseError(status_code=response.status_code, message=sanitized)

        audio = response.content
        if len(audio) < 44 or audio[:4] != b"RIFF" or audio[8:12] != b"WAVE":
            raise TTSParseError("Groq TTS response is not a WAV file")

        return audio

    def close(self) -> None:
        """Close the underlying httpx client if created internally."""
        if not self._external_client:
            self._client.close()

    def __enter__(self) -> "GroqTTSClient":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()


def get_tts_client() -> GroqTTSClient:
    """Dependency injection helper returning a configured GroqTTSClient."""
    return GroqTTSClient()
