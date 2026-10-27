from __future__ import annotations

import base64
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
        use_stream=kwargs.pop("use_stream", False),
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
    assert c2.fallback.use_stream is True
    c2.close()


# -----------------------------------------------------------------------------
# Dedicated Download Timeout & Streaming Tests
# -----------------------------------------------------------------------------


def test_tts_ai_polling_near_timeout_download_succeeds_with_dedicated_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verifies that when polling completes near the timeout limit (e.g. at 29s out of 30s),

    the download succeeds using its dedicated download timeout rather than failing immediately.
    """
    current_simulated_time = 1000.0

    def mock_monotonic() -> float:
        return current_simulated_time

    def mock_sleep(seconds: float) -> None:
        nonlocal current_simulated_time
        current_simulated_time += seconds

    monkeypatch.setattr("app.ai.tts.time.monotonic", mock_monotonic)
    monkeypatch.setattr("app.ai.tts.time.sleep", mock_sleep)

    poll_count = 0
    audio = _wav(sample_rate=24000)

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal poll_count, current_simulated_time
        if request.url == httpx.URL("https://api.tts.ai/v1/tts/"):
            return httpx.Response(200, json={"uuid": "boundary-job-789", "status": "queued"})
        elif request.url == httpx.URL("https://api.tts.ai/v1/speech/results/?uuid=boundary-job-789"):
            poll_count += 1
            if poll_count < 28:
                return httpx.Response(200, json={"status": "processing"})
            # Returns completed at 28 attempts (27 seconds of simulated sleep)
            return httpx.Response(
                200,
                json={"status": "completed", "result_url": "https://cdn.tts.ai/boundary-job-789/out.wav"},
            )
        elif request.url == httpx.URL("https://cdn.tts.ai/boundary-job-789/out.wav"):
            # Download takes 4.0s of simulated time
            current_simulated_time += 4.0
            return httpx.Response(200, content=audio, headers={"content-type": "audio/wav"})
        return httpx.Response(404)

    client = _tts_ai_client(
        handler,
        default_timeout=30.0,
        download_timeout=10.0,
        max_poll_attempts=30,
        poll_interval=1.0,
        use_stream=False,
    )

    result = client.synthesize("Testing polling near timeout limit")

    assert result == audio
    # Polling took 27s + download took 4s = 31s elapsed total (> 30s polling timeout)
    total_elapsed = current_simulated_time - 1000.0
    assert total_elapsed > 30.0
    # But strictly within max_total_timeout (45.0s)
    assert total_elapsed < 45.0
    assert result[:4] == b"RIFF"
    assert result[8:12] == b"WAVE"


def test_tts_ai_download_timeout_raises_unavailable() -> None:
    """Verifies that if CDN download exceeds the dedicated download timeout, TTSUnavailableError is raised."""
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url == httpx.URL("https://api.tts.ai/v1/tts/"):
            return httpx.Response(200, json={"uuid": "hang-dl-job", "status": "queued"})
        elif "speech/results" in str(request.url):
            return httpx.Response(
                200,
                json={"status": "completed", "result_url": "https://cdn.tts.ai/hang-dl-job/out.wav"},
            )
        elif "cdn.tts.ai" in str(request.url):
            raise httpx.ReadTimeout("CDN download timed out", request=request)
        return httpx.Response(404)

    client = _tts_ai_client(handler, download_timeout=5.0, use_stream=False)
    with pytest.raises(TTSUnavailableError) as exc_info:
        client.synthesize("Testing CDN download timeout")

    assert "download timed out" in str(exc_info.value).lower()


def test_tts_ai_download_invalid_sample_rate_raises_parse_error() -> None:
    """Verifies that WAV files with non-24kHz sample rates are rejected with TTSParseError."""
    # Create 16kHz audio (wrong sample rate according to 24kHz contract)
    wrong_rate_audio = _wav(sample_rate=16000)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url == httpx.URL("https://api.tts.ai/v1/tts/"):
            return httpx.Response(200, json={"uuid": "bad-rate-job", "status": "queued"})
        elif "speech/results" in str(request.url):
            return httpx.Response(
                200,
                json={"status": "completed", "result_url": "https://cdn.tts.ai/bad-rate-job/out.wav"},
            )
        elif "cdn.tts.ai" in str(request.url):
            return httpx.Response(200, content=wrong_rate_audio, headers={"content-type": "audio/wav"})
        return httpx.Response(404)

    client = _tts_ai_client(handler, use_stream=False)
    with pytest.raises(TTSParseError) as exc_info:
        client.synthesize("Testing wrong sample rate rejection")

    assert "24 kHz" in str(exc_info.value)


def test_tts_ai_streaming_single_chunk_sse_success() -> None:
    """Verifies that POST /v1/tts/stream/ SSE response delivers 24 kHz mono 16-bit PCM WAV."""
    audio = _wav(sample_rate=24000)
    audio_b64 = base64.b64encode(audio).decode("ascii")

    sse_body = (
        f'data: {{"chunk": "{audio_b64}", "index": 0, "sample_rate": 24000}}\n\n'
        f'data: {{"done": true, "total_chunks": 1, "result_url": "https://cdn.tts.ai/s-123/out.wav"}}\n\n'
    )

    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        if request.url == httpx.URL("https://api.tts.ai/v1/tts/stream/"):
            return httpx.Response(
                200,
                content=sse_body.encode("utf-8"),
                headers={"content-type": "text/event-stream; charset=utf-8"},
            )
        return httpx.Response(404)

    client = _tts_ai_client(handler, use_stream=True)
    result = client.synthesize("Testing SSE streaming endpoint")

    assert len(captured) == 1
    assert captured[0].method == "POST"
    assert captured[0].url == httpx.URL("https://api.tts.ai/v1/tts/stream/")
    payload = json.loads(captured[0].content)
    assert payload["text"] == "Testing SSE streaming endpoint"
    assert payload["model"] == "kokoro"
    assert payload["voice"] == "af_heart"
    assert payload["format"] == "wav"
    assert payload["language"] == "en"

    assert result == audio
    assert result[:4] == b"RIFF"
    assert result[8:12] == b"WAVE"


def test_tts_ai_streaming_multi_chunk_assembly() -> None:
    """Verifies that multiple SSE audio chunks are properly concatenated into a valid 24 kHz WAV."""
    buf1 = io.BytesIO()
    with wave.open(buf1, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(b"\x00\x00" * 240)  # 10ms of silence
    chunk1_wav = buf1.getvalue()
    chunk1_b64 = base64.b64encode(chunk1_wav).decode("ascii")

    # Second chunk: raw PCM
    chunk2_pcm = b"\x01\x00" * 240
    chunk2_b64 = base64.b64encode(chunk2_pcm).decode("ascii")

    sse_body = (
        f'data: {{"chunk": "{chunk1_b64}", "index": 0, "sample_rate": 24000}}\n\n'
        f'data: {{"chunk": "{chunk2_b64}", "index": 1, "sample_rate": 24000}}\n\n'
        f'data: {{"done": true, "total_chunks": 2, "result_url": "https://cdn.tts.ai/multi/out.wav"}}\n\n'
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=sse_body.encode("utf-8"),
            headers={"content-type": "text/event-stream"},
        )

    client = _tts_ai_client(handler, use_stream=True)
    result = client.synthesize("Testing multi-chunk SSE stream assembly")

    assert len(result) >= 44
    assert result[:4] == b"RIFF"
    assert result[8:12] == b"WAVE"
    with wave.open(io.BytesIO(result), "rb") as w:
        assert w.getnchannels() == 1
        assert w.getsampwidth() == 2
        assert w.getframerate() == 24000
        assert w.getnframes() == 480  # 240 + 240 frames


def test_tts_ai_streaming_cached_json_response() -> None:
    """Verifies that if stream endpoint returns application/json (cached), it downloads and validates the WAV."""
    audio = _wav(sample_rate=24000)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url == httpx.URL("https://api.tts.ai/v1/tts/stream/"):
            return httpx.Response(
                200,
                json={"status": "cached", "result_url": "https://cdn.tts.ai/cached/out.wav", "uuid": "c-123"},
                headers={"content-type": "application/json"},
            )
        elif request.url == httpx.URL("https://cdn.tts.ai/cached/out.wav"):
            return httpx.Response(200, content=audio, headers={"content-type": "audio/wav"})
        return httpx.Response(404)

    client = _tts_ai_client(handler, use_stream=True)
    result = client.synthesize("Testing cached stream response")

    assert result == audio


def test_tts_ai_streaming_404_falls_back_to_polling() -> None:
    """Verifies that if /v1/tts/stream/ returns 404, the client seamlessly falls back to /v1/tts/ polling."""
    audio = _wav(sample_rate=24000)
    requests_made: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests_made.append(request)
        if request.url == httpx.URL("https://api.tts.ai/v1/tts/stream/"):
            return httpx.Response(404, json={"detail": "Not Found"})
        elif request.url == httpx.URL("https://api.tts.ai/v1/tts/"):
            return httpx.Response(200, json={"uuid": "fb-poll-123", "status": "queued"})
        elif request.url == httpx.URL("https://api.tts.ai/v1/speech/results/?uuid=fb-poll-123"):
            return httpx.Response(200, json={"status": "completed", "result_url": "https://cdn.tts.ai/fb/out.wav"})
        elif request.url == httpx.URL("https://cdn.tts.ai/fb/out.wav"):
            return httpx.Response(200, content=audio, headers={"content-type": "audio/wav"})
        return httpx.Response(404)

    client = _tts_ai_client(handler, use_stream=True)
    result = client.synthesize("Testing stream 404 fallback to polling")

    assert result == audio
    assert len(requests_made) == 4
    assert requests_made[0].url == httpx.URL("https://api.tts.ai/v1/tts/stream/")
    assert requests_made[1].url == httpx.URL("https://api.tts.ai/v1/tts/")


def test_tts_ai_streaming_invalid_wav_raises_parse_error() -> None:
    """Verifies that corrupted SSE audio chunks raise TTSParseError."""
    sse_body = (
        'data: {"chunk": "bm90IGEgcmVhbCB3YXYgYXVkaW8=", "index": 0, "sample_rate": 24000}\n\n'
        'data: {"done": true, "total_chunks": 1, "result_url": "https://cdn.tts.ai/bad/out.wav"}\n\n'
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=sse_body.encode("utf-8"),
            headers={"content-type": "text/event-stream"},
        )

    client = _tts_ai_client(handler, use_stream=True)
    with pytest.raises(TTSParseError):
        client.synthesize("Testing corrupted SSE stream")


def test_tts_ai_hard_total_timeout_limit_aborts_download(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifies that if total elapsed time across all stages reaches max_total_timeout, it aborts."""
    current_simulated_time = 1000.0

    def mock_monotonic() -> float:
        return current_simulated_time

    monkeypatch.setattr("app.ai.tts.time.monotonic", mock_monotonic)

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal current_simulated_time
        if request.url == httpx.URL("https://api.tts.ai/v1/tts/"):
            return httpx.Response(200, json={"uuid": "huge-delay-job", "status": "queued"})
        elif "speech/results" in str(request.url):
            # Advance simulated time past max_total_timeout (45s)
            current_simulated_time += 50.0
            return httpx.Response(200, json={"status": "completed", "result_url": "https://cdn.tts.ai/huge/out.wav"})
        return httpx.Response(404)

    client = _tts_ai_client(
        handler,
        default_timeout=60.0,
        download_timeout=10.0,
        max_total_timeout=45.0,
        use_stream=False,
    )

    with pytest.raises(TTSUnavailableError) as exc_info:
        client.synthesize("Testing hard total timeout cap")

    assert "exceeded" in str(exc_info.value).lower() and "limit" in str(exc_info.value).lower()


def test_tts_ai_streaming_exceeds_total_timeout_raises_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verifies that if SSE streaming duration exceeds max_total_timeout, it cleanly aborts without hanging."""
    current_simulated_time = 1000.0

    def mock_monotonic() -> float:
        return current_simulated_time

    monkeypatch.setattr("app.ai.tts.time.monotonic", mock_monotonic)

    class SimulatedStreamingBody(httpx.SyncByteStream):
        def __iter__(self):
            nonlocal current_simulated_time
            yield b'data: {"chunk": "UklGRg==", "index": 0, "sample_rate": 24000}\n\n'
            current_simulated_time += 50.0
            yield b'data: {"chunk": "UklGRg==", "index": 1, "sample_rate": 24000}\n\n'

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            stream=SimulatedStreamingBody(),
            headers={"content-type": "text/event-stream"},
        )

    client = _tts_ai_client(
        handler,
        default_timeout=30.0,
        max_total_timeout=45.0,
        use_stream=True,
    )

    with pytest.raises(TTSUnavailableError) as exc_info:
        client.synthesize("Testing streaming total timeout exceeded")

    assert "exceeded total timeout limit" in str(exc_info.value).lower()
