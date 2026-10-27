from __future__ import annotations

import io
import json
import wave

import httpx
import pytest

from app.ai.speech_sanitizer import sanitize_for_speech
from app.ai.tts import (
    MAX_TTS_INPUT_CHARS,
    FallbackTTSClient,
    GroqTTSClient,
    TTSAiClient,
    TTSConfigurationError,
    TTSParseError,
    TTSResponseError,
    TTSUnavailableError,
    TTSValidationError,
    get_tts_client,
)
from app.config import Settings

TEST_API_KEY = "gsk_test_groq_secret_key_1234567890abcdef"
TEST_BASE_URL = "https://api.groq.com/openai/v1"
TEST_TTS_AI_KEY = "tts_ai_secret_token_12345678"
TEST_TTS_AI_BASE = "https://api.tts.ai/v1/"



def _wav(sample_rate: int = 24000, seconds: float = 0.1) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(b"\x00\x00" * int(sample_rate * seconds))
    return buf.getvalue()


def _client(handler, **kwargs) -> GroqTTSClient:
    return GroqTTSClient(
        api_key=kwargs.pop("api_key", TEST_API_KEY),
        base_url=TEST_BASE_URL,
        default_model="canopylabs/orpheus-v1-english",
        default_voice="troy",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        **kwargs,
    )


# -----------------------------------------------------------------------------
# GroqTTSClient Tests
# -----------------------------------------------------------------------------


def test_defaults_come_from_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(
        GROQ_API_KEY=TEST_API_KEY,
        TTS_MODEL="some/model",
        TTS_VOICE="hannah",
        TTS_TIMEOUT_SECONDS=4.5,
        _env_file=None,
    )
    monkeypatch.setattr("app.ai.tts.get_settings", lambda: settings)

    client = GroqTTSClient()
    assert client.default_model == "some/model"
    assert client.default_voice == "hannah"
    assert client.default_timeout == 4.5
    client.close()


def test_synthesize_posts_speech_request_and_returns_wav() -> None:
    captured: list[httpx.Request] = []
    audio = _wav()

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, content=audio, headers={"content-type": "audio/wav"})

    result = _client(handler).synthesize("  Tamam, kaydettim.  ")

    assert result == audio
    req = captured[0]
    assert req.url == httpx.URL("https://api.groq.com/openai/v1/audio/speech")
    assert req.headers["authorization"] == f"Bearer {TEST_API_KEY}"
    parsed_payload = json.loads(req.content)
    assert parsed_payload["model"] == "canopylabs/orpheus-v1-english"
    assert parsed_payload["voice"] == "troy"
    assert parsed_payload["response_format"] == "wav"


def test_synthesize_caps_input_length() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, content=_wav())

    _client(handler).synthesize("a" * (MAX_TTS_INPUT_CHARS + 100))
    assert len(json.loads(captured[0].content)["input"]) <= MAX_TTS_INPUT_CHARS


def test_synthesize_rejects_empty_text() -> None:
    with pytest.raises(TTSValidationError):
        _client(lambda r: httpx.Response(200, content=_wav())).synthesize("   ")


def test_synthesize_requires_api_key() -> None:
    with pytest.raises(TTSConfigurationError):
        _client(lambda r: httpx.Response(200, content=_wav()), api_key="").synthesize("hi")


def test_server_error_maps_to_unavailable() -> None:
    with pytest.raises(TTSUnavailableError):
        _client(lambda r: httpx.Response(503, text="busy")).synthesize("hi")


def test_timeout_maps_to_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(TTSUnavailableError):
        _client(handler).synthesize("hi")


def test_client_error_is_sanitized() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text=f"bad key {TEST_API_KEY}")

    with pytest.raises(TTSResponseError) as exc_info:
        _client(handler).synthesize("hi")
    assert exc_info.value.status_code == 401
    assert TEST_API_KEY not in str(exc_info.value)
    assert "[REDACTED_API_KEY]" in exc_info.value.message


def test_non_wav_body_is_parse_error() -> None:
    with pytest.raises(TTSParseError):
        _client(lambda r: httpx.Response(200, json={"error": "nope"})).synthesize("hi")


# -----------------------------------------------------------------------------
# Speech Sanitizer Tests
# -----------------------------------------------------------------------------


def test_speech_sanitizer_normalizes_numbers_and_contractions() -> None:
    text = "I'll do 30 mins workout at 08:30 on 2026-10-28."
    clean = sanitize_for_speech(text)
    assert "I will" in clean
    assert "thirty" in clean
    assert "eight thirty AM" in clean
    assert "October twenty eighth" in clean


# -----------------------------------------------------------------------------
# TTSAiClient Tests
# -----------------------------------------------------------------------------


def _tts_ai_client(handler, **kwargs) -> TTSAiClient:
    return TTSAiClient(
        api_key=kwargs.pop("api_key", TEST_TTS_AI_KEY),
        base_url=TEST_TTS_AI_BASE,
        default_model="kokoro",
        default_voice="af_heart",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        max_poll_attempts=kwargs.pop("max_poll_attempts", 3),
        poll_interval=kwargs.pop("poll_interval", 0.001),
        **kwargs,
    )


def test_tts_ai_direct_wav_response() -> None:
    captured: list[httpx.Request] = []
    audio = _wav()

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, content=audio, headers={"content-type": "audio/wav"})

    result = _tts_ai_client(handler).synthesize("Hello from TTS fallback")

    assert result == audio
    req = captured[0]
    assert req.url == httpx.URL("https://api.tts.ai/v1/tts/")
    assert req.headers["authorization"] == f"Bearer {TEST_TTS_AI_KEY}"
    payload = json.loads(req.content)
    assert payload["text"] == "Hello from TTS fallback"
    assert payload["model"] == "kokoro"
    assert payload["voice"] == "af_heart"
    assert payload["format"] == "wav"
    assert payload["language"] == "en"
    assert "response_format" not in payload
    assert "input" not in payload


def test_tts_ai_default_poll_interval_within_official_range() -> None:
    client = TTSAiClient(api_key="dummy")
    assert 1.0 <= client.poll_interval <= 2.0
    assert client.max_poll_attempts == 30
    assert client.default_timeout == 30.0
    client.close()


def test_tts_ai_delayed_async_job_completes_past_10_seconds(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifies that an async job taking >10 seconds completes successfully without real wait."""
    current_simulated_time = 1000.0

    def mock_monotonic() -> float:
        return current_simulated_time

    def mock_sleep(seconds: float) -> None:
        nonlocal current_simulated_time
        current_simulated_time += seconds

    monkeypatch.setattr("app.ai.tts.time.monotonic", mock_monotonic)
    monkeypatch.setattr("app.ai.tts.time.sleep", mock_sleep)

    poll_count = 0
    audio = _wav()

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal poll_count
        if request.url == httpx.URL("https://api.tts.ai/v1/tts/"):
            return httpx.Response(200, json={"uuid": "delayed-job-456", "status": "queued"})
        elif request.url == httpx.URL("https://api.tts.ai/v1/speech/results/?uuid=delayed-job-456"):
            poll_count += 1
            # Takes 15 attempts (14 seconds of simulated polling sleep > 10s old timeout)
            if poll_count < 15:
                return httpx.Response(200, json={"status": "processing"})
            return httpx.Response(
                200,
                json={"status": "completed", "result_url": "https://cdn.tts.ai/delayed-job-456/out.wav"},
            )
        elif request.url == httpx.URL("https://cdn.tts.ai/delayed-job-456/out.wav"):
            return httpx.Response(200, content=audio, headers={"content-type": "audio/wav"})
        return httpx.Response(404)

    client = _tts_ai_client(
        handler,
        default_timeout=30.0,
        max_poll_attempts=30,
        poll_interval=1.0,
    )

    result = client.synthesize("Testing delayed job completion exceeding 10 seconds")

    assert result == audio
    assert poll_count == 15
    # Simulated elapsed time is >= 14s (exceeds the old 10s limit)
    assert (current_simulated_time - 1000.0) >= 14.0
    # But strictly within the 30.0s total timeout
    assert (current_simulated_time - 1000.0) <= 30.0
    assert result[:4] == b"RIFF"
    assert result[8:12] == b"WAVE"


def test_tts_ai_polling_strictly_times_out_at_total_timeout_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifies that polling strictly aborts with TTSUnavailableError when total timeout is exceeded."""
    current_simulated_time = 1000.0

    def mock_monotonic() -> float:
        return current_simulated_time

    def mock_sleep(seconds: float) -> None:
        nonlocal current_simulated_time
        current_simulated_time += seconds

    monkeypatch.setattr("app.ai.tts.time.monotonic", mock_monotonic)
    monkeypatch.setattr("app.ai.tts.time.sleep", mock_sleep)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url == httpx.URL("https://api.tts.ai/v1/tts/"):
            return httpx.Response(200, json={"uuid": "never-completing-job", "status": "queued"})
        elif "speech/results" in str(request.url):
            return httpx.Response(200, json={"status": "processing"})
        return httpx.Response(404)

    client = _tts_ai_client(
        handler,
        default_timeout=30.0,
        max_poll_attempts=50,
        poll_interval=1.0,
    )

    with pytest.raises(TTSUnavailableError) as exc_info:
        client.synthesize("Testing strict 30s timeout enforcement")

    assert "timed out after 30" in str(exc_info.value)
    assert (current_simulated_time - 1000.0) >= 30.0



def test_tts_ai_job_uuid_polling_success() -> None:
    captured: list[httpx.Request] = []
    audio = _wav()

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        if request.url == httpx.URL("https://api.tts.ai/v1/tts/"):
            return httpx.Response(
                200,
                json={"uuid": "job-uuid-123", "status": "queued"},
                headers={"content-type": "application/json"},
            )
        elif request.url == httpx.URL("https://api.tts.ai/v1/speech/results/?uuid=job-uuid-123"):
            return httpx.Response(
                200,
                json={
                    "status": "completed",
                    "result_url": "https://cdn.tts.ai/job-uuid-123/output.wav",
                },
                headers={"content-type": "application/json"},
            )
        elif request.url == httpx.URL("https://cdn.tts.ai/job-uuid-123/output.wav"):
            return httpx.Response(
                200,
                content=audio,
                headers={"content-type": "audio/wav"},
            )
        return httpx.Response(404)

    client = _tts_ai_client(handler)
    result = client.synthesize("Testing asynchronous job polling")

    # Verify flow
    assert len(captured) == 3
    assert captured[0].method == "POST"
    assert captured[0].url == httpx.URL("https://api.tts.ai/v1/tts/")
    init_payload = json.loads(captured[0].content)
    assert init_payload["format"] == "wav"
    assert init_payload["language"] == "en"

    assert captured[1].method == "GET"
    assert captured[1].url == httpx.URL("https://api.tts.ai/v1/speech/results/?uuid=job-uuid-123")

    assert captured[2].method == "GET"
    assert captured[2].url == httpx.URL("https://cdn.tts.ai/job-uuid-123/output.wav")

    # Verify audio content and RIFF/WAVE header
    assert result == audio
    assert len(result) >= 44
    assert result[:4] == b"RIFF"
    assert result[8:12] == b"WAVE"



def test_tts_ai_429_raises_response_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "rate_limit_exceeded"})

    with pytest.raises(TTSResponseError) as exc_info:
        _tts_ai_client(handler).synthesize("Testing 429 rate limit")

    assert exc_info.value.status_code == 429
    assert exc_info.value.provider == "tts.ai"


def test_tts_ai_timeout_raises_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow server", request=request)

    with pytest.raises(TTSUnavailableError):
        _tts_ai_client(handler).synthesize("Testing timeout")


def test_tts_ai_invalid_wav_raises_parse_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"corrupted not a riff wav header", headers={"content-type": "audio/wav"})

    with pytest.raises(TTSParseError):
        _tts_ai_client(handler).synthesize("Testing corrupted audio")


def test_tts_ai_job_failed_raises_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url == httpx.URL("https://api.tts.ai/v1/tts/"):
            return httpx.Response(200, json={"uuid": "failed-job-id", "status": "queued"})
        return httpx.Response(200, json={"status": "failed", "error": "Internal worker error"})

    with pytest.raises(TTSUnavailableError):
        _tts_ai_client(handler).synthesize("Testing failed job")


def test_tts_ai_bearer_token_handling() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, content=_wav(), headers={"content-type": "audio/wav"})

    # Case 1: Key present -> Authorization header sent
    _tts_ai_client(handler, api_key="sk-test-custom-key").synthesize("hello")
    assert captured[-1].headers["authorization"] == "Bearer sk-test-custom-key"

    # Case 2: Key empty -> No Authorization header sent
    _tts_ai_client(handler, api_key="").synthesize("hello")
    assert "authorization" not in captured[-1].headers


# -----------------------------------------------------------------------------
# FallbackTTSClient Tests
# -----------------------------------------------------------------------------


def test_fallback_when_groq_returns_429() -> None:
    groq_audio = _wav()
    tts_ai_audio = _wav(seconds=0.2)

    def groq_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="Rate limit reached")

    def tts_ai_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=tts_ai_audio, headers={"content-type": "audio/wav"})

    primary = _client(groq_handler)
    fallback = _tts_ai_client(tts_ai_handler)

    client = FallbackTTSClient(primary=primary, fallback=fallback)
    result = client.synthesize("Testing 429 fallback to TTS.ai")

    assert result == tts_ai_audio
    client.close()


def test_fallback_when_groq_times_out() -> None:
    tts_ai_audio = _wav(seconds=0.2)

    def groq_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("Groq unavailable", request=request)

    def tts_ai_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=tts_ai_audio, headers={"content-type": "audio/wav"})

    primary = _client(groq_handler)
    fallback = _tts_ai_client(tts_ai_handler)

    client = FallbackTTSClient(primary=primary, fallback=fallback)
    result = client.synthesize("Testing timeout fallback to TTS.ai")

    assert result == tts_ai_audio
    client.close()


def test_fallback_both_providers_fail_raises_error() -> None:
    def groq_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="Groq quota exhausted")

    def tts_ai_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="TTS.ai maintenance")

    primary = _client(groq_handler)
    fallback = _tts_ai_client(tts_ai_handler)

    client = FallbackTTSClient(primary=primary, fallback=fallback)

    with pytest.raises(TTSUnavailableError):
        client.synthesize("Testing both providers failing")
    client.close()


def test_fallback_skips_tts_ai_when_groq_succeeds() -> None:
    groq_audio = _wav()

    def groq_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=groq_audio, headers={"content-type": "audio/wav"})

    def tts_ai_handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("TTS.ai should not be called when Groq succeeds!")

    primary = _client(groq_handler)
    fallback = _tts_ai_client(tts_ai_handler)

    client = FallbackTTSClient(primary=primary, fallback=fallback)
    result = client.synthesize("Testing primary success")

    assert result == groq_audio
    client.close()


def test_get_tts_client_creates_fallback_only_when_key_set(monkeypatch: pytest.MonkeyPatch) -> None:
    # 1. No TTS_AI_API_KEY -> Returns plain GroqTTSClient
    settings_no_key = Settings(
        GROQ_API_KEY=TEST_API_KEY,
        TTS_AI_API_KEY="",
        _env_file=None,
    )
    monkeypatch.setattr("app.ai.tts.get_settings", lambda: settings_no_key)
    c1 = get_tts_client()
    assert isinstance(c1, GroqTTSClient)
    assert not isinstance(c1, FallbackTTSClient)
    c1.close()

    # 2. TTS_AI_API_KEY set -> Returns FallbackTTSClient with fallback configured
    settings_with_key = Settings(
        GROQ_API_KEY=TEST_API_KEY,
        TTS_AI_API_KEY="sk-tts-ai-secret",
        _env_file=None,
    )
    monkeypatch.setattr("app.ai.tts.get_settings", lambda: settings_with_key)
    c2 = get_tts_client()
    assert isinstance(c2, FallbackTTSClient)
    assert c2.fallback is not None
    assert c2.fallback.default_model == "kokoro"
    assert c2.fallback.default_voice == "af_heart"
    c2.close()
