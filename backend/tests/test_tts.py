from __future__ import annotations

import io
import json
import wave

import httpx
import pytest

from app.ai.reply import build_reply_text
from app.ai.tts import (
    MAX_TTS_INPUT_CHARS,
    GroqTTSClient,
    TTSConfigurationError,
    TTSParseError,
    TTSResponseError,
    TTSUnavailableError,
    TTSValidationError,
)
from app.config import Settings

TEST_API_KEY = "gsk_test_groq_secret_key_1234567890abcdef"
TEST_BASE_URL = "https://api.groq.com/openai/v1"


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
# GroqTTSClient
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
    assert json.loads(req.content) == {
        "model": "canopylabs/orpheus-v1-english",
        "input": "Tamam, kaydettim.",
        "voice": "troy",
        "response_format": "wav",
    }


def test_synthesize_caps_input_length() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, content=_wav())

    _client(handler).synthesize("a" * (MAX_TTS_INPUT_CHARS + 100))
    assert len(json.loads(captured[0].content)["input"]) == MAX_TTS_INPUT_CHARS


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
# build_reply_text
# -----------------------------------------------------------------------------


def _plan(**changes):
    plan = {
        "intent": "create_plan",
        "title": "Koşu",
        "category": "sport",
        "date": "2026-10-19",
        "time": "18:00",
        "duration_minutes": None,
        "recurrence": None,
        "language": "tr",
        "needs_weather_check": False,
        "clarification_question": None,
        "confidence": 0.9,
    }
    plan.update(changes)
    return plan


def test_reply_create_plan_tomorrow_tr() -> None:
    assert build_reply_text(_plan(), today="2026-10-18") == "Tamam, Koşu planını yarın saat 18:00 için kaydettim."


def test_reply_create_plan_today_en() -> None:
    text = build_reply_text(_plan(language="en", title="Run", date="2026-10-18"), today="2026-10-18")
    assert text == "Okay, I saved Run for today at 18:00."


def test_reply_create_plan_other_day_uses_month_name() -> None:
    assert build_reply_text(_plan(date="2026-11-03"), today="2026-10-18") == (
        "Tamam, Koşu planını 3 Kasım saat 18:00 için kaydettim."
    )


def test_reply_clarify_uses_question() -> None:
    plan = _plan(intent="clarify", clarification_question="Saat kaçta?")
    assert build_reply_text(plan) == "Saat kaçta?"


def test_reply_unsupported_has_hint() -> None:
    plan = _plan(intent="unsupported", title=None, category=None, date=None, time=None)
    assert "plana çeviremedim" in build_reply_text(plan)
    assert "couldn't" in build_reply_text({**plan, "language": "en"})
