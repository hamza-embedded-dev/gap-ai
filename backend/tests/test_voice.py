from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import io
from types import SimpleNamespace
from typing import Any
from uuid import uuid4
import wave

from fastapi.testclient import TestClient
from pydantic import SecretStr
import pytest

from app.ai.llm import (
    LLMUnavailableError,
    NebiusLLMClient,
    get_llm_client,
)
from app.ai.stt import (
    GroqWhisperClient,
    STTConfigurationError,
    STTParseError,
    STTResponseError,
    STTUnavailableError,
    get_stt_client,
)
import app.api.plans as plans_api
from app.db.plans import AuthenticatedUser, get_plan_store
from app.main import app

PEPPER = "p" * 32
TOKEN = "valid-test-token"
TOKEN_HASH = hashlib.sha256((TOKEN + PEPPER).encode("utf-8")).hexdigest()
USER_TZ = "Europe/Istanbul"
USER_ID = "user-test-voice-123"


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
        w.writeframes(b"\x00" * (n_frames * channels * sample_width))
    return buf.getvalue()


def _valid_create_plan(**changes: Any) -> dict[str, Any]:
    plan: dict[str, Any] = {
        "intent": "create_plan",
        "title": "Koşu",
        "category": "sport",
        "date": "2026-10-19",
        "time": "18:00",
        "duration_minutes": 60,
        "recurrence": None,
        "language": "tr",
        "needs_weather_check": True,
        "clarification_question": None,
        "confidence": 0.95,
    }
    plan.update(changes)
    return plan


def _valid_clarify(**changes: Any) -> dict[str, Any]:
    plan: dict[str, Any] = {
        "intent": "clarify",
        "title": "Koşu",
        "category": "sport",
        "date": "2026-10-19",
        "time": None,
        "duration_minutes": None,
        "recurrence": None,
        "language": "tr",
        "needs_weather_check": True,
        "clarification_question": "Koşuya saat kaçta çıkmak istersiniz?",
        "confidence": 0.85,
    }
    plan.update(changes)
    return plan


def _valid_unsupported(**changes: Any) -> dict[str, Any]:
    plan: dict[str, Any] = {
        "intent": "unsupported",
        "title": None,
        "category": None,
        "date": None,
        "time": None,
        "duration_minutes": None,
        "recurrence": None,
        "language": "tr",
        "needs_weather_check": False,
        "clarification_question": None,
        "confidence": 0.99,
    }
    plan.update(changes)
    return plan


class FakePlanStore:
    def __init__(self) -> None:
        user = AuthenticatedUser(
            id=USER_ID,
            timezone=USER_TZ,
            is_demo=False,
            demo_expires_at=None,
        )
        self.tokens = {TOKEN_HASH: (user, None)}
        self.created_plans: list[dict[str, Any]] = []

    def get_user_for_token_hash(self, token_hash: str) -> tuple[AuthenticatedUser, str | None] | None:
        return self.tokens.get(token_hash)

    def create_plan(self, plan: dict[str, Any]) -> dict[str, Any]:
        snapshot = {
            "id": str(uuid4()),
            "title": plan["title"],
            "category": plan["category"],
            "planned_start": plan["planned_start"],
            "planned_end": plan["planned_end"],
            "recurrence_rule": plan.get("recurrence_rule"),
            "source": plan["source"],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "latest_outcome": None,
        }
        self.created_plans.append(snapshot)
        return snapshot


class FakeSTTClient:
    def __init__(self, transcript: str = "Yarın 18'de koşuya çıkacağım.", exception: Exception | None = None) -> None:
        self.transcript = transcript
        self.exception = exception
        self.calls: list[dict[str, Any]] = []

    def validate_wav_audio(self, audio_bytes: bytes, max_seconds: float = 10.0) -> None:
        # Re-use real validation logic from GroqWhisperClient to ensure real WAV checking
        GroqWhisperClient.validate_wav_audio(audio_bytes, max_seconds=max_seconds)

    def transcribe(
        self,
        audio: bytes | Any,
        *,
        model: str | None = None,
        language: str | None = None,
        temperature: float = 0.0,
        prompt: str | None = None,
        timeout: float | None = None,
        validate_audio: bool | None = None,
    ) -> str:
        self.calls.append({
            "audio_len": len(audio) if isinstance(audio, bytes) else None,
            "language": language,
        })
        if self.exception is not None:
            raise self.exception
        return self.transcript


class FakeLLMClient:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = list(responses)
        self.calls: list[list[dict[str, str]]] = []

    def complete_json(self, messages: list[dict[str, str]], **kwargs: Any) -> dict[str, Any]:
        self.calls.append(messages)
        if not self.responses:
            raise RuntimeError("FakeLLMClient ran out of mock responses.")
        next_resp = self.responses.pop(0)
        if isinstance(next_resp, Exception):
            raise next_resp
        return next_resp


@pytest.fixture(autouse=True)
def _patch_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = SimpleNamespace(
        token_hash_pepper=SecretStr(PEPPER),
        environment="development",
        allowed_origins=[],
    )
    monkeypatch.setattr(plans_api, "get_settings", lambda: settings)


@pytest.fixture
def fake_store() -> FakePlanStore:
    store = FakePlanStore()
    app.dependency_overrides[get_plan_store] = lambda: store
    yield store
    app.dependency_overrides.pop(get_plan_store, None)


@pytest.fixture
def client(fake_store: FakePlanStore) -> TestClient:
    return TestClient(app)


def _auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


# =============================================================================
# 1. Authentication Tests
# =============================================================================


def test_voice_endpoint_requires_auth(client: TestClient) -> None:
    wav_bytes = _make_wav_bytes(duration_seconds=1.0)
    response = client.post(
        "/voice",
        files={"audio": ("sample.wav", wav_bytes, "audio/wav")},
    )
    assert response.status_code == 401
    assert response.json() == {"error": "unauthorized", "message": "Token is missing or invalid."}


def test_voice_endpoint_rejects_invalid_token(client: TestClient) -> None:
    wav_bytes = _make_wav_bytes(duration_seconds=1.0)
    response = client.post(
        "/voice",
        headers={"Authorization": "Bearer invalid-token"},
        files={"audio": ("sample.wav", wav_bytes, "audio/wav")},
    )
    assert response.status_code == 401
    assert response.json() == {"error": "unauthorized", "message": "Token is missing or invalid."}


# =============================================================================
# 2. Payload Size and 320 KB Streaming Limit Tests (KK-3)
# =============================================================================


def test_voice_rejects_file_exceeding_320kb(client: TestClient) -> None:
    stt = FakeSTTClient()
    app.dependency_overrides[get_stt_client] = lambda: stt

    # 320 KB limit: 320 * 1024 = 327,680 bytes. Create payload with 327,681 bytes.
    oversized_bytes = b"\x00" * (320 * 1024 + 1)
    response = client.post(
        "/voice",
        headers=_auth_headers(),
        files={"audio": ("large.wav", oversized_bytes, "audio/wav")},
    )
    assert response.status_code == 413
    assert response.json()["error"] == "payload_too_large"
    # STT must NOT be called when payload exceeds size limit
    assert len(stt.calls) == 0


def test_voice_accepts_exactly_10s_wav(client: TestClient, fake_store: FakePlanStore) -> None:
    # 10.0 seconds of 16 kHz 16-bit mono WAV = 320,044 bytes (under 327,680 bytes)
    wav_10s = _make_wav_bytes(duration_seconds=10.0)
    assert len(wav_10s) <= 320 * 1024

    stt = FakeSTTClient(transcript="Yarın 18'de koşuya çıkacağım.")
    llm = FakeLLMClient([_valid_create_plan()])
    app.dependency_overrides[get_stt_client] = lambda: stt
    app.dependency_overrides[get_llm_client] = lambda: llm

    response = client.post(
        "/voice",
        headers=_auth_headers(),
        files={"audio": ("sample_10s.wav", wav_10s, "audio/wav")},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["transcript"] == "Yarın 18'de koşuya çıkacağım."
    assert data["plan"]["source"] == "voice"


# =============================================================================
# 3. Audio Format Validation Tests (KK-4)
# =============================================================================


def test_voice_rejects_empty_file(client: TestClient) -> None:
    response = client.post(
        "/voice",
        headers=_auth_headers(),
        files={"audio": ("empty.wav", b"", "audio/wav")},
    )
    assert response.status_code == 422
    assert response.json()["error"] == "validation_error"


def test_voice_rejects_corrupted_wav(client: TestClient) -> None:
    response = client.post(
        "/voice",
        headers=_auth_headers(),
        files={"audio": ("corrupt.wav", b"RIFFxxxxWAVEfmt not-a-wav", "audio/wav")},
    )
    assert response.status_code == 422
    assert response.json()["error"] == "validation_error"


def test_voice_rejects_stereo_audio(client: TestClient) -> None:
    stereo_wav = _make_wav_bytes(channels=2, sample_rate=16000, duration_seconds=1.0)
    response = client.post(
        "/voice",
        headers=_auth_headers(),
        files={"audio": ("stereo.wav", stereo_wav, "audio/wav")},
    )
    assert response.status_code == 422
    assert response.json()["error"] == "validation_error"
    assert "mono" in response.json()["message"].lower()


def test_voice_rejects_wrong_sample_rate(client: TestClient) -> None:
    wav_44k = _make_wav_bytes(channels=1, sample_rate=44100, duration_seconds=1.0)
    response = client.post(
        "/voice",
        headers=_auth_headers(),
        files={"audio": ("44k.wav", wav_44k, "audio/wav")},
    )
    assert response.status_code == 422
    assert response.json()["error"] == "validation_error"
    assert "16000" in response.json()["message"]


def test_voice_rejects_audio_longer_than_10s(client: TestClient) -> None:
    # 10.5 seconds audio (under 320 KB if generated without header or smaller width)
    # 10.5 * 16000 * 2 = 336,000 bytes > 320 KB, but let's test duration check at 10.1s
    # 10.1s * 16000 * 2 = 323,200 bytes + 44 = 323,244 bytes <= 327,680 bytes (320 KiB)!
    wav_10_1s = _make_wav_bytes(duration_seconds=10.1)
    assert len(wav_10_1s) <= 320 * 1024  # Within byte size, but exceeds 10s duration constraint

    response = client.post(
        "/voice",
        headers=_auth_headers(),
        files={"audio": ("10_1s.wav", wav_10_1s, "audio/wav")},
    )
    assert response.status_code == 422
    assert response.json()["error"] == "validation_error"
    assert "exceeds maximum allowed 10.0 seconds" in response.json()["message"]


# =============================================================================
# 4. Form Fields & Timezone Validation Tests (KK-5)
# =============================================================================


def test_voice_rejects_mismatched_timezone(client: TestClient) -> None:
    wav = _make_wav_bytes(duration_seconds=1.0)
    response = client.post(
        "/voice",
        headers=_auth_headers(),
        data={"timezone": "America/New_York"},
        files={"audio": ("sample.wav", wav, "audio/wav")},
    )
    assert response.status_code == 422
    assert response.json()["error"] == "validation_error"
    assert "does not match registered user timezone" in response.json()["message"]


def test_voice_rejects_invalid_date(client: TestClient) -> None:
    wav = _make_wav_bytes(duration_seconds=1.0)
    response = client.post(
        "/voice",
        headers=_auth_headers(),
        data={"current_date": "not-a-date"},
        files={"audio": ("sample.wav", wav, "audio/wav")},
    )
    assert response.status_code == 422
    assert response.json()["error"] == "validation_error"


# =============================================================================
# 5. Successful create_plan Flow (KK-7, K-3 source: "voice")
# =============================================================================


def test_voice_create_plan_success_flow(client: TestClient, fake_store: FakePlanStore) -> None:
    wav = _make_wav_bytes(duration_seconds=2.0)
    stt = FakeSTTClient(transcript="Yarın saat 18:00'de koşuya çıkacağım.")
    llm = FakeLLMClient([_valid_create_plan()])
    app.dependency_overrides[get_stt_client] = lambda: stt
    app.dependency_overrides[get_llm_client] = lambda: llm

    response = client.post(
        "/voice",
        headers=_auth_headers(),
        data={"language": "tr", "current_date": "2026-10-18", "timezone": USER_TZ},
        files={"audio": ("sample.wav", wav, "audio/wav")},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["transcript"] == "Yarın saat 18:00'de koşuya çıkacağım."
    assert body["parsed_plan"]["intent"] == "create_plan"
    assert body["parsed_plan"]["title"] == "Koşu"
    assert "plan" in body
    assert body["plan"]["source"] == "voice"
    assert body["plan"]["title"] == "Koşu"
    assert body["plan"]["category"] == "sport"
    assert len(fake_store.created_plans) == 1
    assert fake_store.created_plans[0]["source"] == "voice"


# =============================================================================
# 6. Clarify and Unsupported Flows (KK-8)
# =============================================================================


def test_voice_clarify_flow_does_not_persist_plan(client: TestClient, fake_store: FakePlanStore) -> None:
    wav = _make_wav_bytes(duration_seconds=1.5)
    stt = FakeSTTClient(transcript="Koşuya çıkacağım.")
    llm = FakeLLMClient([_valid_clarify()])
    app.dependency_overrides[get_stt_client] = lambda: stt
    app.dependency_overrides[get_llm_client] = lambda: llm

    response = client.post(
        "/voice",
        headers=_auth_headers(),
        files={"audio": ("sample.wav", wav, "audio/wav")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["transcript"] == "Koşuya çıkacağım."
    assert body["parsed_plan"]["intent"] == "clarify"
    assert body["parsed_plan"]["clarification_question"] == "Koşuya saat kaçta çıkmak istersiniz?"
    assert "plan" not in body
    # Veritabanına kesinlikle plan kaydedilmemeli
    assert len(fake_store.created_plans) == 0


def test_voice_unsupported_flow_does_not_persist_plan(client: TestClient, fake_store: FakePlanStore) -> None:
    wav = _make_wav_bytes(duration_seconds=1.5)
    stt = FakeSTTClient(transcript="Bana fıkra anlat.")
    llm = FakeLLMClient([_valid_unsupported()])
    app.dependency_overrides[get_stt_client] = lambda: stt
    app.dependency_overrides[get_llm_client] = lambda: llm

    response = client.post(
        "/voice",
        headers=_auth_headers(),
        files={"audio": ("sample.wav", wav, "audio/wav")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["transcript"] == "Bana fıkra anlat."
    assert body["parsed_plan"]["intent"] == "unsupported"
    assert "plan" not in body
    assert len(fake_store.created_plans) == 0


# =============================================================================
# 7. STT & LLM Error Handling Tests (KK-9)
# =============================================================================


def test_voice_stt_unavailable_returns_503(client: TestClient) -> None:
    wav = _make_wav_bytes(duration_seconds=1.0)
    stt = FakeSTTClient(exception=STTUnavailableError("Groq STT timed out"))
    app.dependency_overrides[get_stt_client] = lambda: stt

    response = client.post(
        "/voice",
        headers=_auth_headers(),
        files={"audio": ("sample.wav", wav, "audio/wav")},
    )
    assert response.status_code == 503
    assert response.json()["error"] == "llm_unavailable"


def test_voice_stt_client_error_returns_503(client: TestClient) -> None:
    wav = _make_wav_bytes(duration_seconds=1.0)
    stt = FakeSTTClient(exception=STTResponseError(status_code=400, message="Bad request"))
    app.dependency_overrides[get_stt_client] = lambda: stt

    response = client.post(
        "/voice",
        headers=_auth_headers(),
        files={"audio": ("sample.wav", wav, "audio/wav")},
    )
    assert response.status_code == 503
    assert response.json()["error"] == "llm_unavailable"


def test_voice_stt_config_error_returns_503(client: TestClient) -> None:
    wav = _make_wav_bytes(duration_seconds=1.0)
    stt = FakeSTTClient(exception=STTConfigurationError("Missing GROQ_API_KEY"))
    app.dependency_overrides[get_stt_client] = lambda: stt

    response = client.post(
        "/voice",
        headers=_auth_headers(),
        files={"audio": ("sample.wav", wav, "audio/wav")},
    )
    assert response.status_code == 503
    assert response.json()["error"] == "llm_unavailable"


def test_voice_stt_parse_error_returns_502(client: TestClient) -> None:
    wav = _make_wav_bytes(duration_seconds=1.0)
    stt = FakeSTTClient(exception=STTParseError("Invalid JSON from Groq"))
    app.dependency_overrides[get_stt_client] = lambda: stt

    response = client.post(
        "/voice",
        headers=_auth_headers(),
        files={"audio": ("sample.wav", wav, "audio/wav")},
    )
    assert response.status_code == 502
    assert response.json()["error"] == "parse_failed"


def test_voice_empty_transcription_returns_422(client: TestClient) -> None:
    wav = _make_wav_bytes(duration_seconds=1.0)
    stt = FakeSTTClient(transcript="   ")
    app.dependency_overrides[get_stt_client] = lambda: stt

    response = client.post(
        "/voice",
        headers=_auth_headers(),
        files={"audio": ("sample.wav", wav, "audio/wav")},
    )
    assert response.status_code == 422
    assert response.json()["error"] == "validation_error"


def test_voice_llm_unavailable_returns_503(client: TestClient) -> None:
    wav = _make_wav_bytes(duration_seconds=1.0)
    stt = FakeSTTClient(transcript="Yarın koşuya çıkacağım.")
    llm = FakeLLMClient([LLMUnavailableError("Nebius LLM timed out")])
    app.dependency_overrides[get_stt_client] = lambda: stt
    app.dependency_overrides[get_llm_client] = lambda: llm

    response = client.post(
        "/voice",
        headers=_auth_headers(),
        files={"audio": ("sample.wav", wav, "audio/wav")},
    )
    assert response.status_code == 503
    assert response.json()["error"] == "llm_unavailable"
