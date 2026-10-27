from __future__ import annotations

import base64
import io
import json
import logging
import struct
import time
from typing import Any
import wave

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

    Supports both immediate WAV SSE stream responses via /tts/stream/ and async
    UUID polling via /speech/results/?uuid=...
    """

    def __init__(
        self,
        api_key: str | SecretStr | None = None,
        base_url: str | None = None,
        default_model: str | None = None,
        default_voice: str | None = None,
        default_timeout: float | None = None,
        download_timeout: float | None = None,
        http_client: httpx.Client | None = None,
        max_poll_attempts: int = 30,
        poll_interval: float = 1.0,
        use_stream: bool | None = None,
        max_total_timeout: float | None = None,
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
            else settings.tts_ai_timeout_seconds or 30.0
        )
        self._download_timeout = (
            download_timeout
            if download_timeout is not None
            else getattr(settings, "tts_ai_download_timeout_seconds", 10.0)
        )
        self._max_poll_attempts = max_poll_attempts
        self._poll_interval = poll_interval
        self._use_stream = (
            use_stream
            if use_stream is not None
            else getattr(settings, "tts_ai_use_stream", True)
        )
        self._max_total_timeout = (
            max_total_timeout
            if max_total_timeout is not None
            else (self._default_timeout + self._download_timeout + 5.0)
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

    @property
    def download_timeout(self) -> float:
        return self._download_timeout

    @property
    def poll_interval(self) -> float:
        return self._poll_interval

    @property
    def max_poll_attempts(self) -> int:
        return self._max_poll_attempts

    @property
    def use_stream(self) -> bool:
        return self._use_stream

    @property
    def max_total_timeout(self) -> float:
        return self._max_total_timeout

    def _stream_url(self) -> str:
        return f"{self._base_url.rstrip('/')}/tts/stream/"

    def _tts_url(self) -> str:
        return f"{self._base_url.rstrip('/')}/tts/"

    def _poll_url(self, uuid: str) -> str:
        return f"{self._base_url.rstrip('/')}/speech/results/?uuid={uuid}"

    def _build_auth_headers(self) -> dict[str, str]:
        headers = {"Accept": "audio/wav, application/json, text/event-stream"}
        if self._api_key and self._api_key.get_secret_value().strip():
            headers["Authorization"] = f"Bearer {self._api_key.get_secret_value().strip()}"
        return headers

    def _validate_wav(self, audio: bytes) -> bytes:
        """Validates that audio is a valid 24 kHz, mono, 16-bit uncompressed PCM WAV file."""
        if len(audio) < 44 or audio[:4] != b"RIFF" or audio[8:12] != b"WAVE":
            raise TTSParseError("TTS.ai response is not a valid WAV file")

        try:
            with wave.open(io.BytesIO(audio), "rb") as w:
                channels = w.getnchannels()
                sampwidth = w.getsampwidth()
                framerate = w.getframerate()
                comptype = w.getcomptype()

                if channels != 1:
                    raise TTSParseError(f"TTS.ai WAV is not mono (channels={channels})")
                if sampwidth != 2:
                    raise TTSParseError(f"TTS.ai WAV is not 16-bit PCM (sampwidth={sampwidth})")
                if framerate != 24000:
                    raise TTSParseError(f"TTS.ai WAV is not 24 kHz (framerate={framerate})")
                if comptype != "NONE":
                    raise TTSParseError(f"TTS.ai WAV is compressed ({comptype}), expected uncompressed PCM")
        except wave.Error as exc:
            raise TTSParseError(f"TTS.ai WAV header parsing error: {exc}") from exc

        return audio

    def _assemble_wav_chunks(self, chunks: list[bytes]) -> bytes:
        """Assembles one or more base64-decoded audio chunks into a valid 24 kHz, mono, 16-bit PCM WAV."""
        if not chunks:
            return b""
        if len(chunks) == 1:
            return chunks[0]

        pcm_data = bytearray()
        for chunk in chunks:
            if len(chunk) >= 44 and chunk[:4] == b"RIFF" and chunk[8:12] == b"WAVE":
                data_marker = chunk.find(b"data")
                if data_marker != -1 and len(chunk) >= data_marker + 8:
                    pcm_data.extend(chunk[data_marker + 8:])
                else:
                    pcm_data.extend(chunk[44:])
            else:
                pcm_data.extend(chunk)

        total_pcm_len = len(pcm_data)
        riff_len = total_pcm_len + 36
        header = struct.pack(
            "<4sI4s4sIHHIIHH4sI",
            b"RIFF",
            riff_len,
            b"WAVE",
            b"fmt ",
            16,       # Subchunk1Size for PCM
            1,        # AudioFormat: 1 = PCM
            1,        # NumChannels: 1 = Mono
            24000,    # SampleRate: 24 kHz
            48000,    # ByteRate: 24000 * 1 * 2
            2,        # BlockAlign: 1 * 2
            16,       # BitsPerSample: 16
            b"data",
            total_pcm_len,
        )
        return header + bytes(pcm_data)

    def _parse_sse_events(self, text: str) -> tuple[list[bytes], str | None]:
        """Parses Server-Sent Events from TTS.ai /tts/stream/ response.

        Returns a tuple of (list of audio chunk bytes, optional result_url).
        """
        chunks: list[bytes] = []
        result_url: str | None = None

        for line in text.splitlines():
            line = line.strip()
            if not line or not line.startswith("data:"):
                continue
            payload_str = line[5:].strip()
            try:
                data = json.loads(payload_str)
            except Exception:
                continue

            if isinstance(data, dict):
                chunk_b64 = data.get("chunk")
                if chunk_b64 and isinstance(chunk_b64, str):
                    try:
                        chunks.append(base64.b64decode(chunk_b64))
                    except Exception as exc:
                        logger.warning("Failed to decode base64 chunk from TTS.ai SSE stream: %s", type(exc).__name__)

                url = data.get("result_url") or data.get("url")
                if url and isinstance(url, str):
                    result_url = url

        return chunks, result_url

    def synthesize(
        self,
        text: str,
        *,
        model: str | None = None,
        voice: str | None = None,
        language: str | None = None,
        format: str | None = None,
        timeout: float | None = None,
        stream: bool | None = None,
    ) -> bytes:
        """Converts text to speech via TTS.ai and returns the WAV file bytes."""
        cleaned = sanitize_for_speech(text)
        if not cleaned:
            raise TTSValidationError("Text to synthesize is empty.")
        cleaned = cleaned[:MAX_TTS_INPUT_CHARS]

        call_timeout = timeout if timeout is not None else self._default_timeout
        start_time = time.monotonic()
        use_stream = self._use_stream if stream is None else stream

        if use_stream:
            return self._synthesize_stream(
                cleaned,
                model=model,
                voice=voice,
                language=language,
                format=format,
                call_timeout=call_timeout,
                start_time=start_time,
            )

        return self._synthesize_poll(
            cleaned,
            model=model,
            voice=voice,
            language=language,
            format=format,
            call_timeout=call_timeout,
            start_time=start_time,
        )

    def _synthesize_stream(
        self,
        cleaned: str,
        *,
        model: str | None = None,
        voice: str | None = None,
        language: str | None = None,
        format: str | None = None,
        call_timeout: float,
        start_time: float,
    ) -> bytes:
        stream_url = self._stream_url()
        headers = self._build_auth_headers()
        headers["Content-Type"] = "application/json"

        payload: dict[str, Any] = {
            "text": cleaned,
            "model": model or self._default_model,
            "voice": voice or self._default_voice,
            "format": format or "wav",
            "language": language or "en",
        }

        t_post_start = time.monotonic()
        try:
            with self._client.stream(
                "POST",
                stream_url,
                json=payload,
                headers=headers,
                timeout=call_timeout,
            ) as response:
                post_duration = time.monotonic() - t_post_start
                logger.info(
                    "TTS.ai stream connected (status=%d, duration=%.2fs)",
                    response.status_code,
                    post_duration,
                )

                if response.status_code == 429:
                    logger.warning("TTS.ai stream returned HTTP 429 (duration=%.2fs)", post_duration)
                    raise TTSResponseError(429, "TTS.ai rate limit exceeded", provider="tts.ai")

                if response.status_code >= 500:
                    logger.error("TTS.ai stream returned server error HTTP %d (duration=%.2fs)", response.status_code, post_duration)
                    raise TTSUnavailableError(f"TTS.ai provider returned server error HTTP {response.status_code}")

                if response.status_code == 404:
                    logger.warning("TTS.ai stream endpoint returned 404, falling back to polling endpoint")
                    return self._synthesize_poll(
                        cleaned,
                        model=model,
                        voice=voice,
                        language=language,
                        format=format,
                        call_timeout=call_timeout,
                        start_time=start_time,
                    )

                if response.status_code >= 400:
                    logger.warning("TTS.ai stream returned client error HTTP %d (duration=%.2fs)", response.status_code, post_duration)
                    raise TTSResponseError(
                        status_code=response.status_code,
                        message=f"TTS.ai client error HTTP {response.status_code}",
                        provider="tts.ai",
                    )

                content_type = response.headers.get("content-type", "").lower()

                # 1. Direct WAV response
                if "audio/wav" in content_type:
                    audio_content = response.read()
                    return self._validate_wav(audio_content)

                # 2. SSE event-stream response: process lines as they arrive
                if "text/event-stream" in content_type:
                    chunks: list[bytes] = []
                    result_url: str | None = None

                    for line in response.iter_lines():
                        elapsed = time.monotonic() - start_time
                        if elapsed >= self._max_total_timeout:
                            logger.warning(
                                "TTS.ai streaming exceeded total timeout limit (duration=%.2fs, limit=%.2fs)",
                                elapsed,
                                self._max_total_timeout,
                            )
                            raise TTSUnavailableError(
                                f"TTS.ai streaming exceeded total timeout limit of {self._max_total_timeout}s"
                            )

                        line = line.strip()
                        if not line or not line.startswith("data:"):
                            continue

                        payload_str = line[5:].strip()
                        try:
                            data = json.loads(payload_str)
                        except Exception:
                            continue

                        if isinstance(data, dict):
                            chunk_b64 = data.get("chunk")
                            if chunk_b64 and isinstance(chunk_b64, str):
                                try:
                                    chunks.append(base64.b64decode(chunk_b64))
                                except Exception as exc:
                                    logger.warning(
                                        "Failed to decode base64 chunk from TTS.ai SSE stream: %s",
                                        type(exc).__name__,
                                    )

                            url = data.get("result_url") or data.get("url")
                            if url and isinstance(url, str):
                                result_url = url

                            if data.get("done"):
                                break

                    if chunks:
                        audio = self._assemble_wav_chunks(chunks)
                        stream_duration = time.monotonic() - start_time
                        logger.info(
                            "TTS.ai stream completed (chunks=%d, bytes=%d, duration=%.2fs)",
                            len(chunks),
                            len(audio),
                            stream_duration,
                        )
                        return self._validate_wav(audio)
                    elif result_url:
                        logger.info("TTS.ai stream completed with result URL, downloading WAV...")
                        return self._download_wav(result_url, start_time=start_time)
                    else:
                        raise TTSParseError("TTS.ai stream response contained neither audio chunks nor result URL")

                # 3. JSON response (cached or UUID)
                body = response.read()
                if body[:4] == b"RIFF":
                    return self._validate_wav(body)

                try:
                    data = json.loads(body.decode("utf-8", errors="replace"))
                except Exception as exc:
                    raise TTSParseError("TTS.ai stream response is neither WAV, SSE, nor valid JSON") from exc

                status = str(data.get("status", "")).lower()
                result_url = data.get("result_url") or data.get("url")
                if status in ("cached", "completed") and result_url:
                    logger.info("TTS.ai stream returned cached/completed audio, downloading WAV...")
                    return self._download_wav(result_url, start_time=start_time)

                job_uuid = data.get("uuid") or data.get("job_id")
                if job_uuid:
                    return self._poll_and_download(str(job_uuid), start_time, call_timeout)

                raise TTSParseError("TTS.ai stream response missing audio and job UUID")
        except (httpx.TimeoutException, TimeoutError) as exc:
            duration = time.monotonic() - t_post_start
            logger.warning("TTS.ai stream call timed out (duration=%.2fs)", duration)
            raise TTSUnavailableError(f"TTS.ai stream request timed out after {call_timeout}s") from exc
        except (httpx.ConnectError, httpx.NetworkError) as exc:
            duration = time.monotonic() - t_post_start
            logger.warning("TTS.ai stream network connection error (duration=%.2fs)", duration)
            raise TTSUnavailableError("Failed to connect to TTS.ai streaming provider") from exc
        except httpx.HTTPError as exc:
            duration = time.monotonic() - t_post_start
            logger.warning("TTS.ai stream transport error: %s (duration=%.2fs)", type(exc).__name__, duration)
            raise TTSUnavailableError(f"TTS.ai stream transport error: {type(exc).__name__}") from exc

    def _synthesize_poll(
        self,
        cleaned: str,
        *,
        model: str | None = None,
        voice: str | None = None,
        language: str | None = None,
        format: str | None = None,
        call_timeout: float,
        start_time: float,
    ) -> bytes:
        headers = self._build_auth_headers()
        headers["Content-Type"] = "application/json"
        payload: dict[str, Any] = {
            "text": cleaned,
            "model": model or self._default_model,
            "voice": voice or self._default_voice,
            "format": format or "wav",
            "language": language or "en",
        }

        t_post_start = time.monotonic()
        try:
            response = self._client.post(
                self._tts_url(),
                json=payload,
                headers=headers,
                timeout=call_timeout,
            )
        except (httpx.TimeoutException, TimeoutError) as exc:
            duration = time.monotonic() - t_post_start
            logger.warning("TTS.ai call timed out (duration=%.2fs)", duration)
            raise TTSUnavailableError(f"TTS.ai request timed out after {call_timeout}s") from exc
        except (httpx.ConnectError, httpx.NetworkError) as exc:
            duration = time.monotonic() - t_post_start
            logger.warning("TTS.ai network connection error (duration=%.2fs)", duration)
            raise TTSUnavailableError("Failed to connect to TTS.ai provider") from exc
        except httpx.HTTPError as exc:
            duration = time.monotonic() - t_post_start
            logger.warning("TTS.ai transport error: %s (duration=%.2fs)", type(exc).__name__, duration)
            raise TTSUnavailableError(f"TTS.ai transport error: {type(exc).__name__}") from exc

        post_duration = time.monotonic() - t_post_start
        logger.info("TTS.ai POST request completed (status=%d, duration=%.2fs)", response.status_code, post_duration)

        if response.status_code == 429:
            logger.warning("TTS.ai returned HTTP 429 (duration=%.2fs)", post_duration)
            raise TTSResponseError(429, "TTS.ai rate limit exceeded", provider="tts.ai")

        if response.status_code >= 500:
            logger.error("TTS.ai returned server error HTTP %d (duration=%.2fs)", response.status_code, post_duration)
            raise TTSUnavailableError(
                f"TTS.ai provider returned server error HTTP {response.status_code}"
            )

        if response.status_code >= 400:
            logger.warning("TTS.ai returned client error HTTP %d (duration=%.2fs)", response.status_code, post_duration)
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

        if data.get("status") in ("completed", "cached") and (data.get("result_url") or data.get("url")):
            return self._download_wav(data.get("result_url") or data.get("url"), start_time=start_time)

        job_uuid = data.get("uuid") or data.get("job_id")
        if not job_uuid:
            raise TTSParseError("TTS.ai response missing job UUID and audio")

        return self._poll_and_download(str(job_uuid), start_time, call_timeout)

    def _poll_and_download(self, job_uuid: str, start_time: float, call_timeout: float) -> bytes:
        poll_url = self._poll_url(job_uuid)
        poll_headers = self._build_auth_headers()
        t_poll_start = time.monotonic()

        for attempt in range(self._max_poll_attempts):
            elapsed = time.monotonic() - start_time
            if elapsed >= self._max_total_timeout:
                logger.warning(
                    "TTS.ai polling exceeded total timeout limit (duration=%.2fs, limit=%.2fs)",
                    elapsed,
                    self._max_total_timeout,
                )
                raise TTSUnavailableError(
                    f"TTS.ai polling exceeded total timeout limit of {self._max_total_timeout}s"
                )
            remaining = call_timeout - elapsed
            if remaining <= 0:
                logger.warning(
                    "TTS.ai polling timed out (attempts=%d, duration=%.2fs)",
                    attempt,
                    time.monotonic() - t_poll_start,
                )
                raise TTSUnavailableError(f"TTS.ai job polling timed out after {call_timeout}s")

            if attempt > 0:
                sleep_dur = min(self._poll_interval, remaining)
                time.sleep(sleep_dur)
                elapsed = time.monotonic() - start_time
                if elapsed >= self._max_total_timeout:
                    logger.warning(
                        "TTS.ai polling exceeded total timeout limit (duration=%.2fs, limit=%.2fs)",
                        elapsed,
                        self._max_total_timeout,
                    )
                    raise TTSUnavailableError(
                        f"TTS.ai polling exceeded total timeout limit of {self._max_total_timeout}s"
                    )
                remaining = call_timeout - elapsed
                if remaining <= 0:
                    logger.warning(
                        "TTS.ai polling timed out (attempts=%d, duration=%.2fs)",
                        attempt,
                        time.monotonic() - t_poll_start,
                    )
                    raise TTSUnavailableError(f"TTS.ai job polling timed out after {call_timeout}s")

            poll_timeout = min(remaining, self._default_timeout)
            try:
                poll_resp = self._client.get(
                    poll_url,
                    headers=poll_headers,
                    timeout=poll_timeout,
                )
            except (httpx.TimeoutException, TimeoutError) as exc:
                raise TTSUnavailableError("TTS.ai polling request timed out") from exc
            except (httpx.ConnectError, httpx.NetworkError) as exc:
                raise TTSUnavailableError("Failed to connect to TTS.ai during polling") from exc
            except httpx.HTTPError as exc:
                raise TTSUnavailableError(f"TTS.ai polling error: {type(exc).__name__}") from exc

            poll_duration = time.monotonic() - t_poll_start
            if poll_resp.status_code == 429:
                logger.warning("TTS.ai polling returned HTTP 429 (attempts=%d, duration=%.2fs)", attempt + 1, poll_duration)
                raise TTSResponseError(429, "TTS.ai rate limit exceeded during polling", provider="tts.ai")
            if poll_resp.status_code >= 500:
                logger.error("TTS.ai polling returned server error HTTP %d (attempts=%d, duration=%.2fs)", poll_resp.status_code, attempt + 1, poll_duration)
                raise TTSUnavailableError(f"TTS.ai server error HTTP {poll_resp.status_code} during polling")
            if poll_resp.status_code >= 400:
                logger.warning("TTS.ai polling returned client error HTTP %d (attempts=%d, duration=%.2fs)", poll_resp.status_code, attempt + 1, poll_duration)
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
                logger.info(
                    "TTS.ai polling completed (status=%s, attempts=%d, duration=%.2fs)",
                    status,
                    attempt + 1,
                    poll_duration,
                )
                return self._download_wav(result_url, start_time=start_time)
            elif status == "failed":
                logger.warning("TTS.ai speech synthesis job reported failure (attempts=%d, duration=%.2fs)", attempt + 1, poll_duration)
                raise TTSUnavailableError("TTS.ai speech synthesis job reported failure")

        poll_duration = time.monotonic() - t_poll_start
        logger.warning("TTS.ai job did not complete within %d attempts (duration=%.2fs)", self._max_poll_attempts, poll_duration)
        raise TTSUnavailableError(f"TTS.ai job did not complete within {self._max_poll_attempts} attempts")

    def _download_wav(self, result_url: str, *, start_time: float | None = None) -> bytes:
        """Downloads the completed WAV file from result_url incrementally with strict bounded timeouts."""
        now = time.monotonic()
        if start_time is not None:
            total_elapsed = now - start_time
            remaining_total = self._max_total_timeout - total_elapsed
            if remaining_total <= 0:
                logger.warning(
                    "TTS.ai total process exceeded total timeout limit before download (duration=%.2fs, limit=%.2fs)",
                    total_elapsed,
                    self._max_total_timeout,
                )
                raise TTSUnavailableError(
                    f"TTS.ai total process exceeded {self._max_total_timeout}s limit"
                )
            dl_timeout = min(self._download_timeout, remaining_total)
        else:
            dl_timeout = self._download_timeout

        if dl_timeout <= 0:
            raise TTSUnavailableError(
                f"TTS.ai total process exceeded {self._max_total_timeout}s limit"
            )

        t_dl_start = time.monotonic()
        content_buffer = bytearray()

        try:
            with self._client.stream("GET", result_url, timeout=dl_timeout) as dl_resp:
                if dl_resp.status_code != 200:
                    dl_duration = time.monotonic() - t_dl_start
                    logger.warning("TTS.ai download returned HTTP %d (duration=%.2fs)", dl_resp.status_code, dl_duration)
                    raise TTSUnavailableError(f"TTS.ai download returned HTTP {dl_resp.status_code}")

                for chunk in dl_resp.iter_bytes():
                    t_chunk = time.monotonic()
                    if start_time is not None and (t_chunk - start_time) >= self._max_total_timeout:
                        logger.warning(
                            "TTS.ai WAV download exceeded total timeout limit (duration=%.2fs, limit=%.2fs)",
                            t_chunk - start_time,
                            self._max_total_timeout,
                        )
                        raise TTSUnavailableError(
                            f"TTS.ai total process exceeded {self._max_total_timeout}s limit"
                        )
                    if (t_chunk - t_dl_start) >= dl_timeout:
                        logger.warning(
                            "TTS.ai WAV download timed out during stream (duration=%.2fs, limit=%.2fs)",
                            t_chunk - t_dl_start,
                            dl_timeout,
                        )
                        raise TTSUnavailableError(f"TTS.ai WAV download timed out after {dl_timeout}s")
                    content_buffer.extend(chunk)
        except (httpx.TimeoutException, TimeoutError) as exc:
            dl_duration = time.monotonic() - t_dl_start
            logger.warning("TTS.ai WAV download timed out after %.2fs", dl_duration)
            raise TTSUnavailableError(f"TTS.ai WAV download timed out after {dl_timeout}s") from exc
        except (httpx.ConnectError, httpx.NetworkError) as exc:
            dl_duration = time.monotonic() - t_dl_start
            logger.warning("TTS.ai WAV download network error (duration=%.2fs)", dl_duration)
            raise TTSUnavailableError("Failed to connect to TTS.ai CDN during download") from exc
        except TTSUnavailableError:
            raise
        except Exception as exc:
            dl_duration = time.monotonic() - t_dl_start
            logger.warning("TTS.ai WAV download transport error: %s (duration=%.2fs)", type(exc).__name__, dl_duration)
            raise TTSUnavailableError(f"Failed to download audio from TTS.ai: {type(exc).__name__}") from exc

        dl_duration = time.monotonic() - t_dl_start
        if start_time is not None and (time.monotonic() - start_time) >= self._max_total_timeout:
            logger.warning(
                "TTS.ai WAV download exceeded total timeout limit at completion (duration=%.2fs, limit=%.2fs)",
                time.monotonic() - start_time,
                self._max_total_timeout,
            )
            raise TTSUnavailableError(
                f"TTS.ai total process exceeded {self._max_total_timeout}s limit"
            )

        if not content_buffer:
            raise TTSParseError("TTS.ai downloaded WAV is empty")

        audio_bytes = bytes(content_buffer)
        logger.info(
            "TTS.ai WAV download completed (status=%d, bytes=%d, duration=%.2fs)",
            200,
            len(audio_bytes),
            dl_duration,
        )
        return self._validate_wav(audio_bytes)


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
