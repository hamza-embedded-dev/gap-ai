from __future__ import annotations

import io
from pathlib import Path
from typing import Any
import wave

import httpx
from pydantic import SecretStr
import pytest

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
from app.config import Settings

TEST_API_KEY = "gsk_test_groq_secret_key_1234567890abcdef"
TEST_BASE_URL = "https://api.groq.com/openai/v1"
TEST_MODEL = "whisper-large-v3"


def _make_wav_bytes(
    channels: int = 1,
    sample_rate: int = 16000,
    sample_width: int = 2,
    duration_seconds: float = 1.0,
) -> bytes:
    """Generates synthetic in-memory WAV audio bytes matching specified audio parameters."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(sample_width)
        w.setframerate(sample_rate)
        n_frames = int(sample_rate * duration_seconds)
        # 16-bit PCM (sample_width=2) silence
        w.writeframes(b"\x00" * (n_frames * channels * sample_width))
    return buf.getvalue()


# -----------------------------------------------------------------------------
# Configuration and Initialization Tests
# -----------------------------------------------------------------------------


def test_client_initialization_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(
        GROQ_API_KEY=TEST_API_KEY,
        GROQ_BASE_URL=TEST_BASE_URL,
        STT_MODEL=TEST_MODEL,
        GROQ_TIMEOUT_SECONDS=45.0,
        _env_file=None,
    )
    monkeypatch.setattr("app.ai.stt.get_settings", lambda: settings)

    client = GroqWhisperClient()
    assert client.base_url == "https://api.groq.com/openai/v1/"
    assert client.default_model == TEST_MODEL
    assert client.default_timeout == 45.0
    assert client.validate_audio is True
    assert client.max_audio_seconds == 10.0
    client.close()


def test_client_explicit_overrides_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(
        GROQ_API_KEY=TEST_API_KEY,
        _env_file=None,
    )
    monkeypatch.setattr("app.ai.stt.get_settings", lambda: settings)

    client = GroqWhisperClient(
        api_key="override-key",
        base_url="https://custom.groq.internal/v1",
        default_model="whisper-large-v3-turbo",
        default_timeout=15.0,
        validate_audio=False,
        max_audio_seconds=5.0,
    )
    assert client.base_url == "https://custom.groq.internal/v1/"
    assert client.default_model == "whisper-large-v3-turbo"
    assert client.default_timeout == 15.0
    assert client.validate_audio is False
    assert client.max_audio_seconds == 5.0
    client.close()


def test_client_requires_api_key_when_called(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(
        GROQ_API_KEY=None,
        _env_file=None,
    )
    monkeypatch.setattr("app.ai.stt.get_settings", lambda: settings)

    client = GroqWhisperClient(api_key=None)
    audio = _make_wav_bytes()
    with pytest.raises(STTConfigurationError, match="GROQ_API_KEY is missing"):
        client.transcribe(audio)
    client.close()


# -----------------------------------------------------------------------------
# WAV Audio Validation Tests (API Contract: mono, 16 kHz, 16-bit, <=10s)
# -----------------------------------------------------------------------------


def test_validate_wav_valid_audio() -> None:
    valid_wav = _make_wav_bytes(channels=1, sample_rate=16000, sample_width=2, duration_seconds=2.0)
    # Should pass without error
    GroqWhisperClient.validate_wav_audio(valid_wav)


def test_validate_wav_empty_bytes() -> None:
    with pytest.raises(STTValidationError, match="Audio data is empty"):
        GroqWhisperClient.validate_wav_audio(b"")


def test_validate_wav_corrupted_data() -> None:
    corrupted = b"RIFF1234WAVEfmt " + b"\x00" * 20
    with pytest.raises(STTValidationError, match="Invalid or corrupted WAV file"):
        GroqWhisperClient.validate_wav_audio(corrupted)


def test_validate_wav_stereo_rejected() -> None:
    stereo_wav = _make_wav_bytes(channels=2, sample_rate=16000, sample_width=2, duration_seconds=1.0)
    with pytest.raises(STTValidationError, match="Audio must be mono \\(1 channel\\), got 2 channels"):
        GroqWhisperClient.validate_wav_audio(stereo_wav)


def test_validate_wav_unsupported_sample_rate() -> None:
    wav_44k = _make_wav_bytes(channels=1, sample_rate=44100, sample_width=2, duration_seconds=1.0)
    with pytest.raises(STTValidationError, match="Audio sample rate must be 16000 Hz"):
        GroqWhisperClient.validate_wav_audio(wav_44k)

    wav_8k = _make_wav_bytes(channels=1, sample_rate=8000, sample_width=2, duration_seconds=1.0)
    with pytest.raises(STTValidationError, match="Audio sample rate must be 16000 Hz"):
        GroqWhisperClient.validate_wav_audio(wav_8k)


def test_validate_wav_unsupported_sample_width() -> None:
    # 8-bit PCM (sample_width=1)
    wav_8bit = _make_wav_bytes(channels=1, sample_rate=16000, sample_width=1, duration_seconds=1.0)
    with pytest.raises(STTValidationError, match="Audio bit depth must be 16-bit PCM"):
        GroqWhisperClient.validate_wav_audio(wav_8bit)


def test_validate_wav_exceeds_max_duration() -> None:
    long_wav = _make_wav_bytes(channels=1, sample_rate=16000, sample_width=2, duration_seconds=11.0)
    with pytest.raises(STTValidationError, match="exceeds maximum allowed 10.0 seconds"):
        GroqWhisperClient.validate_wav_audio(long_wav, max_seconds=10.0)


# -----------------------------------------------------------------------------
# Input Type Resolution Tests
# -----------------------------------------------------------------------------


def test_input_type_bytes() -> None:
    audio = _make_wav_bytes()
    client = GroqWhisperClient(api_key=TEST_API_KEY)
    assert client._resolve_audio_bytes(audio) == audio
    client.close()


def test_input_type_bytes_io() -> None:
    audio = _make_wav_bytes()
    stream = io.BytesIO(audio)
    client = GroqWhisperClient(api_key=TEST_API_KEY)
    assert client._resolve_audio_bytes(stream) == audio
    client.close()


def test_input_type_file_path(tmp_path: Path) -> None:
    audio = _make_wav_bytes()
    audio_file = tmp_path / "test_sample.wav"
    audio_file.write_bytes(audio)

    client = GroqWhisperClient(api_key=TEST_API_KEY)
    assert client._resolve_audio_bytes(audio_file) == audio
    assert client._resolve_audio_bytes(str(audio_file)) == audio
    client.close()


def test_input_type_nonexistent_file(tmp_path: Path) -> None:
    client = GroqWhisperClient(api_key=TEST_API_KEY)
    missing = tmp_path / "does_not_exist.wav"
    with pytest.raises(STTValidationError, match="Audio file not found"):
        client._resolve_audio_bytes(missing)
    client.close()


def test_input_type_unsupported() -> None:
    client = GroqWhisperClient(api_key=TEST_API_KEY)
    with pytest.raises(STTValidationError, match="Unsupported audio input type: int"):
        client._resolve_audio_bytes(12345)  # type: ignore[arg-type]
    client.close()


# -----------------------------------------------------------------------------
# Successful Mock Transcription Tests (K1 & K2 Mock Path)
# -----------------------------------------------------------------------------


def test_successful_transcribe_mock() -> None:
    captured_requests: list[httpx.Request] = []

    def mock_handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        return httpx.Response(200, json={"text": "Yarın 18'de koşuya çıkacağım."})

    audio = _make_wav_bytes(duration_seconds=1.5)
    transport = httpx.MockTransport(mock_handler)
    with httpx.Client(transport=transport) as http_client:
        client = GroqWhisperClient(
            api_key=TEST_API_KEY,
            base_url=TEST_BASE_URL,
            http_client=http_client,
        )
        result = client.transcribe(audio, language="tr", temperature=0.0)

    assert result == "Yarın 18'de koşuya çıkacağım."
    assert len(captured_requests) == 1
    req = captured_requests[0]

    assert req.url == httpx.URL("https://api.groq.com/openai/v1/audio/transcriptions")
    assert req.headers["authorization"] == f"Bearer {TEST_API_KEY}"
    assert req.headers["accept"] == "application/json"
    assert "multipart/form-data" in req.headers.get("content-type", "")

    # Content contains the wav bytes and multipart fields
    assert b"whisper-large-v3" in req.content
    assert b'name="language"\r\n\r\ntr' in req.content
    assert b'name="temperature"\r\n\r\n0.0' in req.content
    assert b'filename="audio.wav"' in req.content


def test_successful_transcribe_raw_dict() -> None:
    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "text": "Toplantı saat üçte.",
                "x_groq": {"id": "req_12345"},
            },
        )

    audio = _make_wav_bytes()
    transport = httpx.MockTransport(mock_handler)
    with httpx.Client(transport=transport) as http_client:
        client = GroqWhisperClient(
            api_key=TEST_API_KEY,
            http_client=http_client,
        )
        raw_data = client.transcribe_raw(audio)

    assert raw_data["text"] == "Toplantı saat üçte."
    assert raw_data["x_groq"]["id"] == "req_12345"


# -----------------------------------------------------------------------------
# Error Handling: HTTP Errors, Timeouts, Network, and Malformed Responses
# -----------------------------------------------------------------------------


def test_groq_upstream_server_error_500() -> None:
    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="Internal Groq LPU Server Error")

    audio = _make_wav_bytes()
    transport = httpx.MockTransport(mock_handler)
    with httpx.Client(transport=transport) as http_client:
        client = GroqWhisperClient(
            api_key=TEST_API_KEY,
            http_client=http_client,
        )
        with pytest.raises(STTUnavailableError, match="returned server error HTTP 500"):
            client.transcribe(audio)


def test_groq_upstream_server_error_503() -> None:
    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="Groq Service Temporarily Unavailable")

    audio = _make_wav_bytes()
    transport = httpx.MockTransport(mock_handler)
    with httpx.Client(transport=transport) as http_client:
        client = GroqWhisperClient(
            api_key=TEST_API_KEY,
            http_client=http_client,
        )
        with pytest.raises(STTUnavailableError, match="returned server error HTTP 503"):
            client.transcribe(audio)


def test_groq_client_error_400() -> None:
    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text='{"error": {"message": "Invalid audio format"}}')

    audio = _make_wav_bytes()
    transport = httpx.MockTransport(mock_handler)
    with httpx.Client(transport=transport) as http_client:
        client = GroqWhisperClient(
            api_key=TEST_API_KEY,
            http_client=http_client,
        )
        with pytest.raises(STTResponseError) as exc_info:
            client.transcribe(audio)
        assert exc_info.value.status_code == 400
        assert "Invalid audio format" in exc_info.value.message


def test_groq_client_error_401_unauthorized() -> None:
    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text='{"error": {"message": "Invalid API Key"}}')

    audio = _make_wav_bytes()
    transport = httpx.MockTransport(mock_handler)
    with httpx.Client(transport=transport) as http_client:
        client = GroqWhisperClient(
            api_key=TEST_API_KEY,
            http_client=http_client,
        )
        with pytest.raises(STTResponseError) as exc_info:
            client.transcribe(audio)
        assert exc_info.value.status_code == 401


def test_groq_client_error_429_rate_limited() -> None:
    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text='{"error": {"message": "Rate limit reached"}}')

    audio = _make_wav_bytes()
    transport = httpx.MockTransport(mock_handler)
    with httpx.Client(transport=transport) as http_client:
        client = GroqWhisperClient(
            api_key=TEST_API_KEY,
            http_client=http_client,
        )
        with pytest.raises(STTResponseError) as exc_info:
            client.transcribe(audio)
        assert exc_info.value.status_code == 429


def test_groq_timeout_error() -> None:
    def mock_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("Connection timed out")

    audio = _make_wav_bytes()
    transport = httpx.MockTransport(mock_handler)
    with httpx.Client(transport=transport) as http_client:
        client = GroqWhisperClient(
            api_key=TEST_API_KEY,
            http_client=http_client,
        )
        with pytest.raises(STTUnavailableError, match="timed out"):
            client.transcribe(audio)


def test_groq_network_connect_error() -> None:
    def mock_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("DNS lookup failed")

    audio = _make_wav_bytes()
    transport = httpx.MockTransport(mock_handler)
    with httpx.Client(transport=transport) as http_client:
        client = GroqWhisperClient(
            api_key=TEST_API_KEY,
            http_client=http_client,
        )
        with pytest.raises(STTUnavailableError, match="Failed to connect to Groq STT"):
            client.transcribe(audio)


def test_groq_invalid_json_response() -> None:
    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="Not a JSON string {")

    audio = _make_wav_bytes()
    transport = httpx.MockTransport(mock_handler)
    with httpx.Client(transport=transport) as http_client:
        client = GroqWhisperClient(
            api_key=TEST_API_KEY,
            http_client=http_client,
        )
        with pytest.raises(STTParseError, match="not valid JSON"):
            client.transcribe(audio)


def test_groq_missing_text_in_response() -> None:
    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"some_other_field": 123})

    audio = _make_wav_bytes()
    transport = httpx.MockTransport(mock_handler)
    with httpx.Client(transport=transport) as http_client:
        client = GroqWhisperClient(
            api_key=TEST_API_KEY,
            http_client=http_client,
        )
        with pytest.raises(STTParseError, match="missing 'text' field"):
            client.transcribe(audio)


# -----------------------------------------------------------------------------
# Security: Secret Masking / Sanitization in Error Messages
# -----------------------------------------------------------------------------


def test_sanitize_error_message_masks_secret() -> None:
    secret = "gsk_super_secret_groq_key_9999"
    client = GroqWhisperClient(api_key=secret)

    err_text = f"Error occurred while using authorization key: {secret} at endpoint"
    sanitized = client._sanitize_error_message(err_text)

    assert secret not in sanitized
    assert "[REDACTED_API_KEY]" in sanitized
    client.close()


# -----------------------------------------------------------------------------
# Context Manager & Dependency Injection Helper
# -----------------------------------------------------------------------------


def test_context_manager() -> None:
    with GroqWhisperClient(api_key=TEST_API_KEY) as client:
        assert isinstance(client, GroqWhisperClient)


def test_get_stt_client_helper(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(
        GROQ_API_KEY=TEST_API_KEY,
        _env_file=None,
    )
    monkeypatch.setattr("app.ai.stt.get_settings", lambda: settings)

    client = get_stt_client()
    assert isinstance(client, GroqWhisperClient)
    assert client.default_model == "whisper-large-v3"
    client.close()
