from __future__ import annotations

import logging
import time
from typing import Any

import httpx
from pydantic import SecretStr

from app.ai.speech_sanitizer import sanitize_for_speech
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
    """Raised when provider cannot be reached (timeout, connect error, 5xx)."""


class TTSResponseError(TTSError):
    """Raised when provider returns a non-2xx client error (e.g. HTTP 400, 401, 429)."""

    def __init__(self, status_code: int, message: str, provider: str = "groq") -> None:
        super().__init__(f"{provider.capitalize()} API returned HTTP {status_code}: {message}")
        self.status_code = status_code
        self.message = message
        self.provider = provider


class TTSParseError(TTSError):
    """Raised when provider returns a body that is not a valid WAV file."""


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
        cleaned = sanitize_for_speech(text)
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
        t0 = time.monotonic()

        try:
            response = self._client.post(
                self._speech_url(),
                json=payload,
                headers=headers,
                timeout=call_timeout,
            )
        except (httpx.TimeoutException, TimeoutError) as exc:
            duration = time.monotonic() - t0
            logger.warning("Groq TTS call timed out after %s seconds (duration=%.2fs)", call_timeout, duration)
            raise TTSUnavailableError(f"TTS request timed out after {call_timeout}s") from exc
        except (httpx.ConnectError, httpx.NetworkError) as exc:
            duration = time.monotonic() - t0
            logger.warning("Groq TTS network connection error (duration=%.2fs)", duration)
            raise TTSUnavailableError("Failed to connect to Groq TTS provider") from exc
        except httpx.HTTPError as exc:
            duration = time.monotonic() - t0
            logger.warning("Groq TTS HTTP transport error: %s (duration=%.2fs)", type(exc).__name__, duration)
            raise TTSUnavailableError(
                f"Groq TTS transport error: {type(exc).__name__}"
            ) from exc

        duration = time.monotonic() - t0

        if response.status_code >= 500:
            logger.error("Groq TTS returned server error HTTP %d (duration=%.2fs)", response.status_code, duration)
            raise TTSUnavailableError(
                f"Groq TTS provider returned server error HTTP {response.status_code}"
            )

        if response.status_code >= 400:
            sanitized = self._sanitize_error_message(response.text[:300])
            logger.error("Groq TTS returned client error HTTP %d (duration=%.2fs)", response.status_code, duration)
            raise TTSResponseError(status_code=response.status_code, message=sanitized, provider="groq")

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


# -----------------------------------------------------------------------------
# TTS.ai Text-to-Speech Client (Fallback Provider)
# -----------------------------------------------------------------------------


class TTSAiClient:
    """Synchronous HTTP client for TTS.ai (https://api.tts.ai/v1/).

    Supports both immediate WAV stream responses and async UUID polling via
    /speech/results/?uuid=...
    """

    def __init__(
        self,
        api_key: str | SecretStr | None = None,
        base_url: str | None = None,
        default_model: str | None = None,
        default_voice: str | None = None,
        default_timeout: float | None = None,
        http_client: httpx.Client | None = None,
        max_poll_attempts: int = 10,
        poll_interval: float = 0.25,
    ) -> None:
        settings: Settings = get_settings()

        resolved_key = api_key if api_key is not None else settings.tts_ai_api_key
        if isinstance(resolved_key, str):
            self._api_key = SecretStr(resolved_key) if resolved_key else None
        else:
            self._api_key = resolved_key

        raw_base = base_url if base_url is not None else settings.tts_ai_base_url
        self._base_url = (raw_base or "https://api.tts.ai/v1/").rstrip("/") + "/"
        self._default_model = default_model or settings.tts_ai_model or "kokoro"
        self._default_voice = default_voice or settings.tts_ai_voice or "af_heart"
        self._default_timeout = (
            default_timeout
            if default_timeout is not None
            else settings.tts_ai_timeout_seconds or 10.0
        )
        self._max_poll_attempts = max_poll_attempts
        self._poll_interval = poll_interval

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

    def _tts_url(self) -> str:
        return f"{self._base_url.rstrip('/')}/tts/"

    def _poll_url(self, uuid: str) -> str:
        return f"{self._base_url.rstrip('/')}/speech/results/?uuid={uuid}"

    def _build_auth_headers(self) -> dict[str, str]:
        headers = {"Accept": "audio/wav, application/json"}
        if self._api_key and self._api_key.get_secret_value().strip():
            headers["Authorization"] = f"Bearer {self._api_key.get_secret_value().strip()}"
        return headers

    def _validate_wav(self, audio: bytes) -> bytes:
        if len(audio) < 44 or audio[:4] != b"RIFF" or audio[8:12] != b"WAVE":
            raise TTSParseError("TTS.ai response is not a valid WAV file")
        return audio

    def synthesize(
        self,
        text: str,
        *,
        model: str | None = None,
        voice: str | None = None,
        timeout: float | None = None,
    ) -> bytes:
        """Converts text to speech via TTS.ai and returns the WAV file bytes."""
        cleaned = sanitize_for_speech(text)
        if not cleaned:
            raise TTSValidationError("Text to synthesize is empty.")
        cleaned = cleaned[:MAX_TTS_INPUT_CHARS]

        call_timeout = timeout if timeout is not None else self._default_timeout
        start_time = time.monotonic()

        headers = self._build_auth_headers()
        headers["Content-Type"] = "application/json"
        payload = {
            "text": cleaned,
            "input": cleaned,
            "model": model or self._default_model,
            "voice": voice or self._default_voice,
            "response_format": "wav",
        }

        try:
            response = self._client.post(
                self._tts_url(),
                json=payload,
                headers=headers,
                timeout=call_timeout,
            )
        except (httpx.TimeoutException, TimeoutError) as exc:
            duration = time.monotonic() - start_time
            logger.warning("TTS.ai call timed out (duration=%.2fs)", duration)
            raise TTSUnavailableError(f"TTS.ai request timed out after {call_timeout}s") from exc
        except (httpx.ConnectError, httpx.NetworkError) as exc:
            duration = time.monotonic() - start_time
            logger.warning("TTS.ai network connection error (duration=%.2fs)", duration)
            raise TTSUnavailableError("Failed to connect to TTS.ai provider") from exc
        except httpx.HTTPError as exc:
            duration = time.monotonic() - start_time
            logger.warning("TTS.ai transport error: %s (duration=%.2fs)", type(exc).__name__, duration)
            raise TTSUnavailableError(f"TTS.ai transport error: {type(exc).__name__}") from exc

        duration = time.monotonic() - start_time

        if response.status_code == 429:
            logger.warning("TTS.ai returned HTTP 429 (duration=%.2fs)", duration)
            raise TTSResponseError(429, "TTS.ai rate limit exceeded", provider="tts.ai")

        if response.status_code >= 500:
            logger.error("TTS.ai returned server error HTTP %d (duration=%.2fs)", response.status_code, duration)
            raise TTSUnavailableError(
                f"TTS.ai provider returned server error HTTP {response.status_code}"
            )

        if response.status_code >= 400:
            logger.warning("TTS.ai returned client error HTTP %d (duration=%.2fs)", response.status_code, duration)
            raise TTSResponseError(
                status_code=response.status_code,
                message=f"TTS.ai client error HTTP {response.status_code}",
                provider="tts.ai",
            )

        # 1. Direct WAV response
        content_type = response.headers.get("content-type", "").lower()
        if "audio/wav" in content_type or response.content[:4] == b"RIFF":
            return self._validate_wav(response.content)

        # 2. JSON response (either direct result or UUID polling)
        try:
            data = response.json()
        except Exception as exc:
            raise TTSParseError("TTS.ai response is neither WAV nor valid JSON") from exc

        if data.get("status") == "completed" and (data.get("result_url") or data.get("url")):
            return self._download_wav(data.get("result_url") or data.get("url"), start_time, call_timeout)

        job_uuid = data.get("uuid") or data.get("job_id")
        if not job_uuid:
            raise TTSParseError("TTS.ai response missing job UUID and audio")

        return self._poll_and_download(str(job_uuid), start_time, call_timeout)

    def _poll_and_download(self, job_uuid: str, start_time: float, call_timeout: float) -> bytes:
        poll_url = self._poll_url(job_uuid)
        poll_headers = self._build_auth_headers()

        for attempt in range(self._max_poll_attempts):
            elapsed = time.monotonic() - start_time
            remaining = call_timeout - elapsed
            if remaining <= 0:
                logger.warning("TTS.ai polling timed out after %.2fs", elapsed)
                raise TTSUnavailableError(f"TTS.ai job polling timed out after {call_timeout}s")

            if attempt > 0:
                time.sleep(min(self._poll_interval, remaining))

            try:
                poll_resp = self._client.get(
                    poll_url,
                    headers=poll_headers,
                    timeout=min(remaining, self._default_timeout),
                )
            except (httpx.TimeoutException, TimeoutError) as exc:
                raise TTSUnavailableError("TTS.ai polling request timed out") from exc
            except (httpx.ConnectError, httpx.NetworkError) as exc:
                raise TTSUnavailableError("Failed to connect to TTS.ai during polling") from exc
            except httpx.HTTPError as exc:
                raise TTSUnavailableError(f"TTS.ai polling error: {type(exc).__name__}") from exc

            poll_duration = time.monotonic() - start_time
            if poll_resp.status_code == 429:
                logger.warning("TTS.ai polling returned HTTP 429 (duration=%.2fs)", poll_duration)
                raise TTSResponseError(429, "TTS.ai rate limit exceeded during polling", provider="tts.ai")
            if poll_resp.status_code >= 500:
                logger.error("TTS.ai polling returned server error HTTP %d (duration=%.2fs)", poll_resp.status_code, poll_duration)
                raise TTSUnavailableError(f"TTS.ai server error HTTP {poll_resp.status_code} during polling")
            if poll_resp.status_code >= 400:
                logger.warning("TTS.ai polling returned client error HTTP %d (duration=%.2fs)", poll_resp.status_code, poll_duration)
                raise TTSResponseError(
                    poll_resp.status_code,
                    f"TTS.ai polling client error HTTP {poll_resp.status_code}",
                    provider="tts.ai",
                )

            try:
                poll_data = poll_resp.json()
            except Exception as exc:
                raise TTSParseError("TTS.ai polling returned invalid JSON") from exc

            status = str(poll_data.get("status", "")).lower()
            if status == "completed":
                result_url = poll_data.get("result_url") or poll_data.get("url")
                if not result_url:
                    raise TTSParseError("TTS.ai completed job did not return result_url")
                return self._download_wav(result_url, start_time, call_timeout)
            elif status == "failed":
                raise TTSUnavailableError("TTS.ai speech synthesis job reported failure")

        raise TTSUnavailableError(f"TTS.ai job did not complete within {self._max_poll_attempts} attempts")

    def _download_wav(self, result_url: str, start_time: float, call_timeout: float) -> bytes:
        remaining = call_timeout - (time.monotonic() - start_time)
        if remaining <= 0:
            raise TTSUnavailableError(f"TTS.ai download timed out after {call_timeout}s")

        try:
            dl_resp = self._client.get(result_url, timeout=remaining)
        except (httpx.TimeoutException, TimeoutError) as exc:
            raise TTSUnavailableError("TTS.ai WAV download timed out") from exc
        except Exception as exc:
            raise TTSUnavailableError(f"Failed to download audio from TTS.ai: {type(exc).__name__}") from exc

        dl_duration = time.monotonic() - start_time
        if dl_resp.status_code != 200:
            logger.warning("TTS.ai download returned HTTP %d (duration=%.2fs)", dl_resp.status_code, dl_duration)
            raise TTSUnavailableError(f"TTS.ai download returned HTTP {dl_resp.status_code}")

        return self._validate_wav(dl_resp.content)

    def close(self) -> None:
        if not self._external_client:
            self._client.close()

    def __enter__(self) -> "TTSAiClient":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()


# -----------------------------------------------------------------------------
# Fallback Orchestrator (Groq Primary -> TTS.ai Secondary)
# -----------------------------------------------------------------------------


class FallbackTTSClient(GroqTTSClient):
    """Orchestrates primary Groq TTS with automatic fallback to TTS.ai on 429 or transient errors."""

    def __init__(
        self,
        primary: GroqTTSClient,
        fallback: TTSAiClient | None = None,
    ) -> None:
        self._primary = primary
        self._fallback = fallback

    @property
    def primary(self) -> GroqTTSClient:
        return self._primary

    @property
    def fallback(self) -> TTSAiClient | None:
        return self._fallback

    def synthesize(
        self,
        text: str,
        *,
        model: str | None = None,
        voice: str | None = None,
        timeout: float | None = None,
    ) -> bytes:
        cleaned = sanitize_for_speech(text)
        if not cleaned:
            raise TTSValidationError("Text to synthesize is empty.")

        t0 = time.monotonic()
        primary_exc: Exception | None = None
        try:
            audio = self._primary.synthesize(text, model=model, voice=voice, timeout=timeout)
            logger.info("TTS provider=groq succeeded (duration=%.2fs)", time.monotonic() - t0)
            return audio
        except TTSValidationError:
            raise
        except (TTSResponseError, TTSUnavailableError, TTSParseError, TTSConfigurationError) as exc:
            primary_exc = exc
            status_code = getattr(exc, "status_code", None)
            logger.warning(
                "Primary TTS provider=groq failed (error_type=%s, status_code=%s, duration=%.2fs)",
                type(exc).__name__,
                status_code,
                time.monotonic() - t0,
            )

        if self._fallback is None:
            assert primary_exc is not None
            raise primary_exc

        t1 = time.monotonic()
        try:
            logger.info("Attempting fallback TTS provider=tts.ai")
            audio = self._fallback.synthesize(text, timeout=timeout)
            logger.info("Fallback TTS provider=tts.ai succeeded (duration=%.2fs)", time.monotonic() - t1)
            return audio
        except Exception as fb_exc:
            fb_status = getattr(fb_exc, "status_code", None)
            logger.error(
                "Fallback TTS provider=tts.ai failed (error_type=%s, status_code=%s, duration=%.2fs)",
                type(fb_exc).__name__,
                fb_status,
                time.monotonic() - t1,
            )
            raise fb_exc

    def close(self) -> None:
        self._primary.close()
        if self._fallback:
            self._fallback.close()

    def __enter__(self) -> "FallbackTTSClient":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()


def get_tts_client() -> GroqTTSClient:
    """Dependency injection helper returning GroqTTSClient or FallbackTTSClient if TTS.ai key is set."""
    settings = get_settings()
    primary = GroqTTSClient()
    if not settings.tts_enabled:
        return primary

    tts_ai_key = settings.tts_ai_api_key.get_secret_value().strip() if settings.tts_ai_api_key else ""
    if not tts_ai_key:
        return primary

    fallback = TTSAiClient()
    return FallbackTTSClient(primary=primary, fallback=fallback)
