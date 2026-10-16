from __future__ import annotations

import io
import json
import logging
from pathlib import Path
from typing import Any, BinaryIO
import wave

import httpx
from pydantic import SecretStr

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

# API contract & operational defaults (docs/decisions.md D-009, K-7, MAX_AUDIO_SECONDS=10)
MAX_AUDIO_SECONDS_DEFAULT: float = 10.0
SUPPORTED_SAMPLE_RATE: int = 16000
SUPPORTED_CHANNELS: int = 1
SUPPORTED_SAMPLE_WIDTH: int = 2  # 16-bit PCM


# -----------------------------------------------------------------------------
# Exception Hierarchy
# -----------------------------------------------------------------------------


class STTError(Exception):
    """Base exception for all speech-to-text client errors."""


class STTConfigurationError(STTError):
    """Raised when the STT client is misconfigured (e.g. missing GROQ_API_KEY)."""


class STTValidationError(STTError):
    """Raised when audio input is empty, missing, invalid WAV, or violates contract.

    Contract requirements: mono, 16 kHz, 16-bit PCM, <=10s duration.
    Corresponds to contract HTTP 422 validation_error / 413 payload_too_large.
    """


class STTUnavailableError(STTError):
    """Raised when Groq API cannot be reached (timeout, connect error, 5xx).

    Corresponds to contract HTTP 503 llm_unavailable at the API layer.
    """


class STTResponseError(STTError):
    """Raised when Groq returns a non-2xx client error (e.g. HTTP 400, 401, 429)."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(f"Groq API returned HTTP {status_code}: {message}")
        self.status_code = status_code
        self.message = message


class STTParseError(STTError):
    """Raised when Groq response body is invalid JSON or lacks expected text field.

    Corresponds to contract HTTP 502 parse_failed at the API layer.
    """


# -----------------------------------------------------------------------------
# Groq Whisper Speech-to-Text Client
# -----------------------------------------------------------------------------


class GroqWhisperClient:
    """Synchronous HTTP client for Groq Whisper Large V3 speech-to-text.

    Uses the OpenAI-compatible /audio/transcriptions endpoint over httpx.Client.
    Keeps API keys strictly in SecretStr and never leaks secrets in exceptions or logs.
    Strictly validates input WAV files for 16 kHz, mono, 16-bit PCM and duration <=10s.
    """

    def __init__(
        self,
        api_key: str | SecretStr | None = None,
        base_url: str | None = None,
        default_model: str | None = None,
        default_timeout: float | None = None,
        http_client: httpx.Client | None = None,
        validate_audio: bool = True,
        max_audio_seconds: float = MAX_AUDIO_SECONDS_DEFAULT,
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

        self._default_model = (
            default_model
            if default_model is not None
            else settings.stt_model or "whisper-large-v3"
        )

        self._default_timeout = (
            default_timeout
            if default_timeout is not None
            else settings.groq_timeout_seconds or 30.0
        )

        self._validate_audio = validate_audio
        self._max_audio_seconds = max_audio_seconds
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

    @property
    def validate_audio(self) -> bool:
        return self._validate_audio

    @property
    def max_audio_seconds(self) -> float:
        return self._max_audio_seconds

    def _get_api_key_value(self) -> str:
        if not self._api_key or not self._api_key.get_secret_value().strip():
            raise STTConfigurationError(
                "GROQ_API_KEY is missing or empty. Please configure it in your environment."
            )
        return self._api_key.get_secret_value().strip()

    def _build_headers(self) -> dict[str, str]:
        key = self._get_api_key_value()
        return {
            "Authorization": f"Bearer {key}",
            "Accept": "application/json",
        }

    def _transcriptions_url(self) -> str:
        base = self._base_url.rstrip("/")
        if not base.endswith("/audio/transcriptions"):
            if not base.endswith("/v1"):
                base = f"{base}/v1"
            base = f"{base}/audio/transcriptions"
        return base

    def _sanitize_error_message(self, text: str) -> str:
        """Strip raw API key if it somehow appears in upstream error text."""
        if self._api_key:
            raw_key = self._api_key.get_secret_value()
            if raw_key and len(raw_key) > 4 and raw_key in text:
                text = text.replace(raw_key, "[REDACTED_API_KEY]")
        return text

    @staticmethod
    def validate_wav_audio(
        audio_bytes: bytes,
        max_seconds: float = MAX_AUDIO_SECONDS_DEFAULT,
    ) -> None:
        """Validates that audio_bytes represents a valid mono, 16 kHz, 16-bit WAV file within max_seconds.

        Raises STTValidationError if the audio violates contract constraints.
        """
        if not audio_bytes:
            raise STTValidationError("Audio data is empty.")

        try:
            with wave.open(io.BytesIO(audio_bytes), "rb") as wav:
                channels = wav.getnchannels()
                sample_width = wav.getsampwidth()
                frame_rate = wav.getframerate()
                n_frames = wav.getnframes()
        except (wave.Error, EOFError) as exc:
            raise STTValidationError(f"Invalid or corrupted WAV file: {exc}") from exc

        if channels != SUPPORTED_CHANNELS:
            raise STTValidationError(
                f"Audio must be mono (1 channel), got {channels} channels."
            )

        if frame_rate != SUPPORTED_SAMPLE_RATE:
            raise STTValidationError(
                f"Audio sample rate must be {SUPPORTED_SAMPLE_RATE} Hz (16 kHz), got {frame_rate} Hz."
            )

        if sample_width != SUPPORTED_SAMPLE_WIDTH:
            raise STTValidationError(
                f"Audio bit depth must be 16-bit PCM (2 bytes), got {sample_width * 8}-bit."
            )

        if frame_rate > 0:
            duration_seconds = n_frames / float(frame_rate)
            if duration_seconds > max_seconds:
                raise STTValidationError(
                    f"Audio duration ({duration_seconds:.2f}s) exceeds maximum allowed {max_seconds} seconds."
                )

    def _resolve_audio_bytes(self, audio: bytes | BinaryIO | str | Path) -> bytes:
        """Coerces supported audio input types into raw bytes."""
        if isinstance(audio, bytes):
            return audio

        if isinstance(audio, (str, Path)):
            path = Path(audio)
            if not path.is_file():
                raise STTValidationError(f"Audio file not found: {path}")
            try:
                return path.read_bytes()
            except OSError as exc:
                raise STTValidationError(f"Failed to read audio file '{path}': {exc}") from exc

        if hasattr(audio, "read"):
            try:
                content = audio.read()
                if isinstance(content, bytes):
                    return content
                raise STTValidationError("File-like object must return bytes when read.")
            except Exception as exc:
                if isinstance(exc, STTValidationError):
                    raise
                raise STTValidationError(f"Failed to read from audio stream: {exc}") from exc

        raise STTValidationError(
            f"Unsupported audio input type: {type(audio).__name__}. Expected bytes, Path, or binary stream."
        )

    def transcribe_raw(
        self,
        audio: bytes | BinaryIO | str | Path,
        *,
        model: str | None = None,
        language: str | None = None,
        temperature: float = 0.0,
        prompt: str | None = None,
        timeout: float | None = None,
        validate_audio: bool | None = None,
    ) -> dict[str, Any]:
        """Low-level synchronous call to Groq /audio/transcriptions.

        Returns the parsed JSON response dictionary from Groq Cloud.
        """
        audio_bytes = self._resolve_audio_bytes(audio)

        should_validate = (
            validate_audio if validate_audio is not None else self._validate_audio
        )
        if should_validate:
            self.validate_wav_audio(audio_bytes, max_seconds=self._max_audio_seconds)

        url = self._transcriptions_url()
        headers = self._build_headers()
        selected_model = model or self._default_model

        form_data: dict[str, Any] = {
            "model": selected_model,
            "response_format": "json",
            "temperature": str(temperature),
        }
        if language:
            form_data["language"] = language
        if prompt:
            form_data["prompt"] = prompt

        files = {
            "file": ("audio.wav", audio_bytes, "audio/wav"),
        }

        call_timeout = timeout if timeout is not None else self._default_timeout

        try:
            response = self._client.post(
                url,
                data=form_data,
                files=files,
                headers=headers,
                timeout=call_timeout,
            )
        except (httpx.TimeoutException, TimeoutError) as exc:
            logger.warning("Groq STT call timed out after %s seconds", call_timeout)
            raise STTUnavailableError(
                f"STT request timed out after {call_timeout}s"
            ) from exc
        except (httpx.ConnectError, httpx.NetworkError) as exc:
            logger.warning("Groq STT network connection error")
            raise STTUnavailableError(
                "Failed to connect to Groq STT provider"
            ) from exc
        except httpx.HTTPError as exc:
            logger.warning("Groq STT HTTP transport error: %s", type(exc).__name__)
            raise STTUnavailableError(
                f"Groq STT transport error: {type(exc).__name__}"
            ) from exc

        if response.status_code >= 500:
            sanitized = self._sanitize_error_message(response.text[:300])
            logger.error("Groq STT returned server error %d: %s", response.status_code, sanitized)
            raise STTUnavailableError(
                f"Groq STT provider returned server error HTTP {response.status_code}"
            )

        if response.status_code >= 400:
            sanitized = self._sanitize_error_message(response.text[:300])
            logger.error("Groq STT returned client error %d: %s", response.status_code, sanitized)
            raise STTResponseError(
                status_code=response.status_code,
                message=sanitized,
            )

        try:
            data = response.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise STTParseError("Groq STT response body is not valid JSON") from exc

        if not isinstance(data, dict):
            raise STTParseError("Groq STT response body must be a JSON object")

        return data

    def transcribe(
        self,
        audio: bytes | BinaryIO | str | Path,
        *,
        model: str | None = None,
        language: str | None = None,
        temperature: float = 0.0,
        prompt: str | None = None,
        timeout: float | None = None,
        validate_audio: bool | None = None,
    ) -> str:
        """Transcribes input audio and returns the transcript text as a string."""
        data = self.transcribe_raw(
            audio=audio,
            model=model,
            language=language,
            temperature=temperature,
            prompt=prompt,
            timeout=timeout,
            validate_audio=validate_audio,
        )

        text = data.get("text")
        if text is None or not isinstance(text, str):
            raise STTParseError("Groq STT response missing 'text' field or text is not a string")

        return text.strip()

    def close(self) -> None:
        """Close the underlying httpx client if created internally."""
        if not self._external_client:
            self._client.close()

    def __enter__(self) -> "GroqWhisperClient":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()


def get_stt_client() -> GroqWhisperClient:
    """Dependency injection helper returning a configured GroqWhisperClient."""
    return GroqWhisperClient()
