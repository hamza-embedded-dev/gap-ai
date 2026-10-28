from __future__ import annotations

from datetime import datetime, timedelta, timezone
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
    STTTimeoutError,
    STTUnavailableError,
    get_stt_client,
)
from app.ai.tts import get_tts_client
import app.api.plans as plans_api
from app.db.plans import AuthenticatedUser, get_plan_store
from app.schemas.parsed_plan import ParsedPlan
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
        self.historical_plans: list[dict[str, Any]] = []
        self.suggestions: dict[str, dict[str, Any]] = {}
        self.proposals: dict[str, list[dict[str, Any]]] = {}

    def get_user_for_token_hash(self, token_hash: str) -> tuple[AuthenticatedUser, str | None] | None:
        return self.tokens.get(token_hash)

    def create_plan_proposal(
        self,
        *,
        user_id: str,
        proposal: dict[str, Any],
        conversation_id: str | None = None,
    ) -> dict[str, Any]:
        record = {
            "id": str(uuid4()),
            "user_id": user_id,
            "conversation_id": conversation_id,
            "title": proposal["title"],
            "category": proposal.get("category", "sport"),
            "planned_start": proposal["planned_start"],
            "planned_end": proposal["planned_end"],
            "duration_minutes": proposal.get("duration_minutes", 60),
            "recurrence_rule": proposal.get("recurrence_rule"),
            "status": "pending",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self.proposals.setdefault(user_id, []).append(record)
        return record

    def get_latest_pending_proposal(self, *, user_id: str) -> dict[str, Any] | None:
        for p in reversed(self.proposals.get(user_id, [])):
            if p.get("status") == "pending":
                return p
        return None

    def accept_plan_proposal(
        self, *, user_id: str, proposal_id: str | None = None
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        proposal = self.get_latest_pending_proposal(user_id=user_id)
        if not proposal:
            raise ValueError("No pending plan proposal found.")
        if proposal_id and proposal.get("id") != proposal_id:
            raise ValueError("Proposal ID mismatch.")
        proposal["status"] = "accepted"
        plan_record = {
            "user_id": user_id,
            "title": proposal["title"],
            "category": proposal["category"],
            "planned_start": proposal["planned_start"],
            "planned_end": proposal["planned_end"],
            "recurrence_rule": proposal.get("recurrence_rule"),
            "source": "voice",
        }
        created = self.create_plan(plan_record)
        return proposal, created

    def reject_plan_proposal(
        self, *, user_id: str, proposal_id: str | None = None
    ) -> dict[str, Any]:
        proposal = self.get_latest_pending_proposal(user_id=user_id)
        if not proposal:
            raise ValueError("No pending plan proposal found.")
        if proposal_id and proposal.get("id") != proposal_id:
            raise ValueError("Proposal ID mismatch.")
        proposal["status"] = "rejected"
        return proposal

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

    def get_plan(self, *, user_id: str, plan_id: str):
        return next((p for p in self.created_plans if p["id"] == plan_id), None)

    def list_plans(self, *, user_id: str):
        return [p for p in self.historical_plans if p.get("user_id") == user_id] + list(self.created_plans)

    def get_suggestion(self, user_id: str, plan_id: str):
        return self.suggestions.get(f"{user_id}:{plan_id}")

    def save_suggestion(self, user_id: str, plan_id: str, suggestion_data: dict[str, Any]):
        self.suggestions[f"{user_id}:{plan_id}"] = suggestion_data
        return suggestion_data


class FakeSTTClient:
    def __init__(self, transcript: str = "Yarın 18'de koşuya çıkacağım.", exception: Exception | None = None) -> None:
        self.transcript = transcript
        self.exception = exception
        self.calls: list[dict[str, Any]] = []

    def validate_wav_audio(self, audio_bytes: bytes, max_seconds: float = 10.0) -> bytes:
        # Re-use real validation logic from GroqWhisperClient to ensure real WAV checking
        return GroqWhisperClient.validate_wav_audio(audio_bytes, max_seconds=max_seconds)

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


class FakeTTSClient:
    def __init__(self, audio_bytes: bytes | None = None) -> None:
        self.audio_bytes = audio_bytes or _make_wav_bytes(duration_seconds=0.5)
        self.calls: list[str] = []

    def synthesize(self, text: str, **kwargs: Any) -> bytes:
        self.calls.append(text)
        return self.audio_bytes


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


def test_voice_create_plan_success_flow(
    client: TestClient, fake_store: FakePlanStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    wav = _make_wav_bytes(duration_seconds=2.0)
    stt = FakeSTTClient(transcript="Yarın saat 18:00'de koşuya çıkacağım.")
    llm = FakeLLMClient([_valid_create_plan()])
    app.dependency_overrides[get_stt_client] = lambda: stt
    app.dependency_overrides[get_llm_client] = lambda: llm
    recommendation_call: dict[str, Any] = {}

    def recommendation_for_created_plan(*, plan_id: str, user: AuthenticatedUser, store, llm):
        recommendation_call.update(plan_id=plan_id, user=user, store=store, llm=llm)
        return {"suggestion": {"message": "Yarın koşunu aynı saatte denemek ister misin?"}}

    monkeypatch.setattr("app.api.voice.get_suggestion_for_plan", recommendation_for_created_plan)

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
    assert body["spoken_recommendation"] == "Yarın koşunu aynı saatte denemek ister misin?"
    assert recommendation_call["plan_id"] == body["plan"]["id"]
    assert len(fake_store.created_plans) == 1
    assert fake_store.created_plans[0]["source"] == "voice"


def test_voice_spoken_recommendation_matches_saved_plan_recommendation(
    client: TestClient, fake_store: FakePlanStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = datetime.now(timezone.utc)
    for days_ago in (4, 5, 6):
        fake_store.historical_plans.append({
            "id": str(uuid4()),
            "user_id": USER_ID,
            "planned_start": (now - timedelta(days=days_ago, hours=2)).isoformat(),
            "planned_end": (now - timedelta(days=days_ago, hours=1)).isoformat(),
            "latest_outcome": {"status": "skipped", "reported_at": (now - timedelta(days=days_ago)).isoformat()},
        })

    class RecommendationLLM:
        def complete(self, messages, **kwargs):
            return "Geçmiş planlarına göre daha erken bir saat deneyebilirsin."

    llm = RecommendationLLM()
    app.dependency_overrides[get_stt_client] = lambda: FakeSTTClient()
    app.dependency_overrides[get_llm_client] = lambda: llm
    monkeypatch.setattr(
        "app.api.voice.parse_text",
        lambda **kwargs: ParsedPlan(_valid_create_plan(date=(now + timedelta(days=1)).date().isoformat())),
    )
    monkeypatch.setattr("app.api.suggestions.WeatherService.get_forecast", lambda *a, **kw: None)

    response = client.post(
        "/voice",
        headers=_auth_headers(),
        data={"language": "tr", "current_date": now.date().isoformat(), "timezone": USER_TZ},
        files={"audio": ("sample.wav", _make_wav_bytes(), "audio/wav")},
    )

    assert response.status_code == 201
    body = response.json()
    saved = fake_store.get_suggestion(USER_ID, body["plan"]["id"])
    assert saved is not None
    assert body["spoken_recommendation"] == saved["message"]
    assert len(fake_store.suggestions) == 1


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


# =============================================================================
# 8. B5-3 Edge Case Tests: Header Repair, Raw PCM, Timeouts, and Resource Cleanup
# =============================================================================


def test_voice_accepts_wav_with_zero_data_size_header(client: TestClient, fake_store: FakePlanStore) -> None:
    # Simulates ESP32 streaming recording where data_size was left as 0 in header
    wav = bytearray(_make_wav_bytes(duration_seconds=1.0))
    wav[40:44] = b"\x00\x00\x00\x00"

    stt = FakeSTTClient(transcript="Yarın 18'de koşuya çıkacağım.")
    llm = FakeLLMClient([_valid_create_plan()])
    app.dependency_overrides[get_stt_client] = lambda: stt
    app.dependency_overrides[get_llm_client] = lambda: llm

    response = client.post(
        "/voice",
        headers=_auth_headers(),
        files={"audio": ("stream.wav", bytes(wav), "audio/wav")},
    )
    assert response.status_code == 201
    assert response.json()["plan"]["source"] == "voice"
    assert len(fake_store.created_plans) == 1


def test_voice_accepts_wav_with_max_data_size_header(client: TestClient, fake_store: FakePlanStore) -> None:
    # Simulates streaming recording with 0xFFFFFFFF chunk size
    wav = bytearray(_make_wav_bytes(duration_seconds=1.0))
    wav[40:44] = b"\xff\xff\xff\xff"

    stt = FakeSTTClient(transcript="Yarın 18'de koşuya çıkacağım.")
    llm = FakeLLMClient([_valid_create_plan()])
    app.dependency_overrides[get_stt_client] = lambda: stt
    app.dependency_overrides[get_llm_client] = lambda: llm

    response = client.post(
        "/voice",
        headers=_auth_headers(),
        files={"audio": ("stream.wav", bytes(wav), "audio/wav")},
    )
    assert response.status_code == 201
    assert response.json()["plan"]["source"] == "voice"
    assert len(fake_store.created_plans) == 1


def test_voice_accepts_raw_pcm_upload_with_content_type(client: TestClient, fake_store: FakePlanStore) -> None:
    # 0.5s of 16 kHz 16-bit mono PCM = 16,000 bytes (no WAV header)
    pcm_bytes = b"\x00\x00" * 8000

    stt = FakeSTTClient(transcript="Yarın 18'de koşuya çıkacağım.")
    llm = FakeLLMClient([_valid_create_plan()])
    app.dependency_overrides[get_stt_client] = lambda: stt
    app.dependency_overrides[get_llm_client] = lambda: llm

    response = client.post(
        "/voice",
        headers=_auth_headers(),
        files={"audio": ("sample", pcm_bytes, "audio/pcm")},
    )
    assert response.status_code == 201
    assert response.json()["plan"]["source"] == "voice"
    assert len(fake_store.created_plans) == 1


def test_voice_accepts_raw_pcm_upload_with_filename(client: TestClient, fake_store: FakePlanStore) -> None:
    # 0.2s of raw PCM = 6,400 bytes with filename ending in .raw
    pcm_bytes = b"\x00\x00" * 3200

    stt = FakeSTTClient(transcript="Yarın 18'de koşuya çıkacağım.")
    llm = FakeLLMClient([_valid_create_plan()])
    app.dependency_overrides[get_stt_client] = lambda: stt
    app.dependency_overrides[get_llm_client] = lambda: llm

    response = client.post(
        "/voice",
        headers=_auth_headers(),
        files={"audio": ("recording.raw", pcm_bytes, "application/octet-stream")},
    )
    assert response.status_code == 201
    assert response.json()["plan"]["source"] == "voice"
    assert len(fake_store.created_plans) == 1


def test_voice_rejects_truncated_wav(client: TestClient) -> None:
    # Header says 32,000 bytes, but only 200 bytes supplied
    wav = _make_wav_bytes(duration_seconds=1.0)
    truncated = wav[: 44 + 200]

    response = client.post(
        "/voice",
        headers=_auth_headers(),
        files={"audio": ("truncated.wav", truncated, "audio/wav")},
    )
    assert response.status_code == 422
    assert response.json()["error"] == "validation_error"


def test_voice_rejects_odd_raw_pcm(client: TestClient) -> None:
    # Odd byte count raw PCM
    odd_pcm = b"\x00" * 3201

    response = client.post(
        "/voice",
        headers=_auth_headers(),
        files={"audio": ("audio.pcm", odd_pcm, "audio/pcm")},
    )
    assert response.status_code == 422
    assert response.json()["error"] == "validation_error"


def test_voice_rejects_raw_pcm_exceeding_10s(client: TestClient) -> None:
    # 320,002 bytes exceeds 10.0 seconds limit
    long_pcm = b"\x00" * 320002

    response = client.post(
        "/voice",
        headers=_auth_headers(),
        files={"audio": ("long.raw", long_pcm, "audio/raw")},
    )
    assert response.status_code == 422
    assert response.json()["error"] == "validation_error"
    assert "exceeds maximum allowed 10.0 seconds" in response.json()["message"]


def test_voice_rejects_non_wav_magic_bytes(client: TestClient) -> None:
    # Non-WAV file (e.g. MP3) sent with WAV content type must be rejected
    mp3_like = b"ID3\x03\x00\x00\x00\x00\x00\x00" + b"\x00" * 200

    response = client.post(
        "/voice",
        headers=_auth_headers(),
        files={"audio": ("sample.wav", mp3_like, "audio/wav")},
    )
    assert response.status_code == 422
    assert response.json()["error"] == "validation_error"


def test_voice_stt_timeout_returns_503_and_saves_no_plan(client: TestClient, fake_store: FakePlanStore) -> None:
    stt = FakeSTTClient(exception=STTTimeoutError("Groq STT request timed out after 30s"))
    app.dependency_overrides[get_stt_client] = lambda: stt

    response = client.post(
        "/voice",
        headers=_auth_headers(),
        files={"audio": ("sample.wav", _make_wav_bytes(), "audio/wav")},
    )
    assert response.status_code == 503
    assert response.json()["error"] == "llm_unavailable"
    assert "timed out" in response.json()["message"].lower()
    # Critical: verify NO plan was created in store
    assert len(fake_store.created_plans) == 0


def test_voice_stt_connect_error_returns_503_and_saves_no_plan(client: TestClient, fake_store: FakePlanStore) -> None:
    stt = FakeSTTClient(exception=STTUnavailableError("Failed to connect to Groq STT"))
    app.dependency_overrides[get_stt_client] = lambda: stt

    response = client.post(
        "/voice",
        headers=_auth_headers(),
        files={"audio": ("sample.wav", _make_wav_bytes(), "audio/wav")},
    )
    assert response.status_code == 503
    assert response.json()["error"] == "llm_unavailable"
    assert len(fake_store.created_plans) == 0


def test_voice_uploadfile_closed_on_success_and_error(client: TestClient) -> None:
    from unittest.mock import AsyncMock, patch

    stt = FakeSTTClient(transcript="Yarın 18'de koşuya çıkacağım.")
    llm = FakeLLMClient([_valid_create_plan()])
    app.dependency_overrides[get_stt_client] = lambda: stt
    app.dependency_overrides[get_llm_client] = lambda: llm

    # 1. Success path
    with patch("starlette.datastructures.UploadFile.close", new_callable=AsyncMock) as mock_close:
        response = client.post(
            "/voice",
            headers=_auth_headers(),
            files={"audio": ("sample.wav", _make_wav_bytes(), "audio/wav")},
        )
        assert response.status_code == 201
        assert mock_close.await_count >= 1

    # 2. Validation error path (empty file)
    with patch("starlette.datastructures.UploadFile.close", new_callable=AsyncMock) as mock_close:
        response = client.post(
            "/voice",
            headers=_auth_headers(),
            files={"audio": ("sample.wav", b"", "audio/wav")},
        )
        assert response.status_code == 422
        assert mock_close.await_count >= 1

    # 3. STT error path
    stt_err = FakeSTTClient(exception=STTTimeoutError("STT timeout"))
    app.dependency_overrides[get_stt_client] = lambda: stt_err
    with patch("starlette.datastructures.UploadFile.close", new_callable=AsyncMock) as mock_close:
        response = client.post(
            "/voice",
            headers=_auth_headers(),
            files={"audio": ("sample.wav", _make_wav_bytes(), "audio/wav")},
        )
        assert response.status_code == 503
        assert mock_close.await_count >= 1


def test_voice_provides_default_spoken_confirmation_when_recommendation_is_none(
    client: TestClient, fake_store: FakePlanStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    # No historical plans, recommendation service returns None
    from app.api import voice as voice_module
    monkeypatch.setattr(voice_module, "get_suggestion_for_plan", lambda **kwargs: {"suggestion": None})

    payload = _valid_create_plan(title="Gym")
    client.app.dependency_overrides[get_llm_client] = lambda: FakeLLMClient([payload])
    client.app.dependency_overrides[get_stt_client] = lambda: FakeSTTClient(transcript="Tomorrow 8 AM gym")

    wav_bytes = _make_wav_bytes(duration_seconds=1.0)
    response = client.post(
        "/voice",
        files={"audio": ("voice.wav", wav_bytes, "audio/wav")},
        headers=_auth_headers(),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["spoken_recommendation"] == "Plan 'Gym' has been scheduled."
    assert body["plan"]["title"] == "Gym"


def test_voice_returns_wav_audio_when_accept_contains_audio_wav(
    client: TestClient, fake_store: FakePlanStore
) -> None:
    from app.ai.tts import get_tts_client

    fake_wav = _make_wav_bytes(duration_seconds=0.5)

    class FakeTTSClient:
        def synthesize(self, text: str, **kwargs) -> bytes:
            return fake_wav

    payload = _valid_create_plan(title="Tennis")
    client.app.dependency_overrides[get_llm_client] = lambda: FakeLLMClient([payload])
    client.app.dependency_overrides[get_stt_client] = lambda: FakeSTTClient(transcript="Play tennis tomorrow 5 PM")
    client.app.dependency_overrides[get_tts_client] = lambda: FakeTTSClient()

    wav_bytes = _make_wav_bytes(duration_seconds=1.0)
    headers = dict(_auth_headers())
    headers["Accept"] = "audio/wav, application/json"

    response = client.post(
        "/voice",
        files={"audio": ("voice.wav", wav_bytes, "audio/wav")},
        headers=headers,
    )

    assert response.status_code == 201
    assert response.headers["content-type"] == "audio/wav"
    assert response.headers["x-intent"] == "propose_plan"
    assert response.headers["x-needs-button"] == "true"
    assert "x-proposal-id" in response.headers
    assert response.content == fake_wav

    # CRITICAL: Verify plan was NOT saved in store yet (waiting for confirmation button)
    assert len(fake_store.created_plans) == 0
    prop_id = response.headers["x-proposal-id"]
    assert len(fake_store.proposals[USER_ID]) == 1

    # Simulate GPIO 1 button press: POST /plans/proposals/accept
    accept_resp = client.post(
        f"/plans/proposals/accept?proposal_id={prop_id}",
        headers=headers,
    )
    assert accept_resp.status_code == 200
    assert accept_resp.headers["content-type"] == "audio/wav"
    assert accept_resp.headers["x-status"] == "accepted"

    # NOW and ONLY NOW verify plan was saved in store
    assert len(fake_store.created_plans) == 1
    assert fake_store.created_plans[0]["title"] == "Tennis"


def test_voice_returns_wav_audio_on_clarify_without_saving_plan(
    client: TestClient, fake_store: FakePlanStore
) -> None:
    from app.ai.tts import get_tts_client

    fake_wav = _make_wav_bytes(duration_seconds=0.5)

    class FakeTTSClient:
        def synthesize(self, text: str, **kwargs) -> bytes:
            return fake_wav

    clarify_payload = {
        "intent": "clarify",
        "title": "Walk",
        "category": "sport",
        "date": None,
        "time": None,
        "duration_minutes": None,
        "recurrence": None,
        "language": "en",
        "needs_weather_check": False,
        "clarification_question": "What time would you like to take a walk?",
        "confidence": 0.8,
    }
    client.app.dependency_overrides[get_llm_client] = lambda: FakeLLMClient([clarify_payload])
    client.app.dependency_overrides[get_stt_client] = lambda: FakeSTTClient(transcript="Walk")
    client.app.dependency_overrides[get_tts_client] = lambda: FakeTTSClient()

    wav_bytes = _make_wav_bytes(duration_seconds=1.0)
    headers = dict(_auth_headers())
    headers["Accept"] = "audio/wav, application/json"

    response = client.post(
        "/voice",
        files={"audio": ("voice.wav", wav_bytes, "audio/wav")},
        headers=headers,
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    assert response.headers["x-intent"] == "clarify"
    assert response.headers["x-needs-button"] == "false"
    assert response.content == fake_wav
    # Crucial: verify NO plan was saved in store!
    assert len(fake_store.created_plans) == 0


def test_voice_tts_failure_falls_back_to_json_without_duplicate_plan(
    client: TestClient, fake_store: FakePlanStore
) -> None:
    from app.ai.tts import TTSError, get_tts_client

    class FailingTTSClient:
        def synthesize(self, text: str, **kwargs) -> bytes:
            raise TTSError("Groq TTS upstream unavailable")

    payload = _valid_create_plan(title="Swimming")
    client.app.dependency_overrides[get_llm_client] = lambda: FakeLLMClient([payload])
    client.app.dependency_overrides[get_stt_client] = lambda: FakeSTTClient(transcript="Swimming tomorrow 7 AM")
    client.app.dependency_overrides[get_tts_client] = lambda: FailingTTSClient()

    wav_bytes = _make_wav_bytes(duration_seconds=1.0)
    headers = dict(_auth_headers())
    headers["Accept"] = "audio/wav, application/json"

    response = client.post(
        "/voice",
        files={"audio": ("voice.wav", wav_bytes, "audio/wav")},
        headers=headers,
    )

    assert response.status_code == 201
    assert "application/json" in response.headers["content-type"]
    body = response.json()
    assert body["proposal"]["title"] == "Swimming"
    # Plan must NOT be created yet before button press!
    assert len(fake_store.created_plans) == 0


def test_voice_strictly_forces_english_stt_and_parser_when_no_language_specified(
    client: TestClient, fake_store: FakePlanStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verifies that when no language parameter is supplied, STT and parser are strictly given 'en'."""
    stt = FakeSTTClient(transcript="I want to go swimming tomorrow at 6 PM for two hours.")
    client.app.dependency_overrides[get_stt_client] = lambda: stt
    client.app.dependency_overrides[get_tts_client] = lambda: FakeTTSClient()

    captured_kwargs: dict[str, Any] = {}

    def mock_parse_text(**kwargs: Any) -> ParsedPlan:
        captured_kwargs.update(kwargs)
        return ParsedPlan({
            "intent": "create_plan",
            "title": "Swimming",
            "category": "sport",
            "date": "2026-10-29",
            "time": "18:00",
            "duration_minutes": 120,
            "recurrence": None,
            "language": "en",
            "needs_weather_check": False,
            "clarification_question": None,
            "confidence": 0.95,
        })

    monkeypatch.setattr("app.api.voice.parse_text", mock_parse_text)

    response = client.post(
        "/voice",
        headers=_auth_headers(),
        data={"current_date": "2026-10-28", "timezone": USER_TZ},
        files={"audio": ("sample.wav", _make_wav_bytes(), "audio/wav")},
    )

    assert response.status_code == 201
    assert stt.calls[-1]["language"] == "en"
    assert captured_kwargs.get("language") == "en"


def test_voice_strictly_forces_english_stt_and_parser_even_if_tr_requested(
    client: TestClient, fake_store: FakePlanStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verifies that even if a client attempts to pass language='tr', /voice overrides and forces 'en'."""
    stt = FakeSTTClient(transcript="I want to study math tomorrow at 7 PM for one hour.")
    client.app.dependency_overrides[get_stt_client] = lambda: stt
    client.app.dependency_overrides[get_tts_client] = lambda: FakeTTSClient()

    captured_kwargs: dict[str, Any] = {}

    def mock_parse_text(**kwargs: Any) -> ParsedPlan:
        captured_kwargs.update(kwargs)
        return ParsedPlan({
            "intent": "create_plan",
            "title": "Study math",
            "category": "study",
            "date": "2026-10-29",
            "time": "19:00",
            "duration_minutes": 60,
            "recurrence": None,
            "language": "en",
            "needs_weather_check": False,
            "clarification_question": None,
            "confidence": 0.95,
        })

    monkeypatch.setattr("app.api.voice.parse_text", mock_parse_text)

    response = client.post(
        "/voice",
        headers=_auth_headers(),
        data={"language": "tr", "current_date": "2026-10-28", "timezone": USER_TZ},
        files={"audio": ("sample.wav", _make_wav_bytes(), "audio/wav")},
    )

    assert response.status_code == 201
    assert stt.calls[-1]["language"] == "en"
    assert captured_kwargs.get("language") == "en"


def test_parse_text_english_swimming_phrase() -> None:
    """Verifies that 'I want to go swimming tomorrow at 6 PM for two hours.' is parsed correctly."""
    from datetime import date
    from app.api.parse import parse_text
    from tests.test_parse import FakeLLMClient

    today = date(2026, 10, 28)
    expected_date = (today + timedelta(days=1)).isoformat()
    raw_text = "I want to go swimming tomorrow at 6 PM for two hours."

    llm_payload = {
        "intent": "create_plan",
        "title": "Swimming",
        "category": "sport",
        "date": expected_date,
        "time": "18:00",
        "duration_minutes": 120,
        "recurrence": None,
        "language": "en",
        "needs_weather_check": False,
        "clarification_question": None,
        "confidence": 0.95,
    }
    fake_llm = FakeLLMClient([llm_payload])

    parsed = parse_text(
        raw_text,
        current_date=today,
        timezone="Europe/Istanbul",
        language="en",
        llm_client=fake_llm,
    )
    root = parsed.root
    assert root["intent"] == "create_plan"
    assert root["title"] == "Swimming"
    assert root["category"] == "sport"
    assert root["date"] == expected_date
    assert root["time"] == "18:00"
    assert root["duration_minutes"] == 120
    assert root["language"] == "en"

    prompt_user_content = fake_llm.calls[0][1]["content"]
    assert "- Requested Language: en" in prompt_user_content


def test_parse_text_english_study_math_phrase() -> None:
    """Verifies that 'I want to study math tomorrow at 7 PM for one hour.' is parsed correctly."""
    from datetime import date
    from app.api.parse import parse_text
    from tests.test_parse import FakeLLMClient

    today = date(2026, 10, 28)
    expected_date = (today + timedelta(days=1)).isoformat()
    raw_text = "I want to study math tomorrow at 7 PM for one hour."

    llm_payload = {
        "intent": "create_plan",
        "title": "Study math",
        "category": "study",
        "date": expected_date,
        "time": "19:00",
        "duration_minutes": 60,
        "recurrence": None,
        "language": "en",
        "needs_weather_check": False,
        "clarification_question": None,
        "confidence": 0.95,
    }
    fake_llm = FakeLLMClient([llm_payload])

    parsed = parse_text(
        raw_text,
        current_date=today,
        timezone="Europe/Istanbul",
        language="en",
        llm_client=fake_llm,
    )
    root = parsed.root
    assert root["intent"] == "create_plan"
    assert root["title"] == "Study math"
    assert root["category"] == "study"
    assert root["date"] == expected_date
    assert root["time"] == "19:00"
    assert root["duration_minutes"] == 60
    assert root["language"] == "en"

    prompt_user_content = fake_llm.calls[0][1]["content"]
    assert "- Requested Language: en" in prompt_user_content


def test_voice_proposal_rejection_never_saves_plan(
    client: TestClient, fake_store: FakePlanStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verifies that when a drafted proposal is rejected, it is never saved to the plans database."""
    swimming_payload = {
        "intent": "create_plan",
        "title": "Swimming",
        "category": "sport",
        "date": "2026-10-29",
        "time": "18:00",
        "duration_minutes": 120,
        "recurrence": None,
        "language": "en",
        "needs_weather_check": False,
        "clarification_question": None,
        "confidence": 0.95,
    }
    client.app.dependency_overrides[get_stt_client] = lambda: FakeSTTClient(
        transcript="I want to go swimming tomorrow at 6 PM for two hours."
    )
    monkeypatch.setattr("app.api.voice.parse_text", lambda **kwargs: ParsedPlan(swimming_payload))
    client.app.dependency_overrides[get_tts_client] = lambda: FakeTTSClient()

    headers = dict(_auth_headers())
    headers["Accept"] = "audio/wav, application/json"

    # 1. Voice command creates a pending proposal
    response = client.post(
        "/voice",
        files={"audio": ("voice.wav", _make_wav_bytes(), "audio/wav")},
        headers=headers,
    )
    assert response.status_code == 201
    assert response.headers["x-intent"] == "propose_plan"
    assert response.headers["x-needs-button"] == "true"
    proposal_id = response.headers["x-proposal-id"]
    assert proposal_id

    # Verify no plan was created yet
    assert len(fake_store.created_plans) == 0

    # 2. Reject proposal via GPIO 2 endpoint
    reject_resp = client.post(
        f"/plans/proposals/reject?proposal_id={proposal_id}",
        headers=headers,
    )
    assert reject_resp.status_code == 200

    assert reject_resp.headers["x-status"] == "rejected"

    # Verify still NO plan was created in the database store
    assert len(fake_store.created_plans) == 0



def test_voice_endpoint_falls_back_to_tts_ai_on_groq_429(
    client: TestClient, fake_store: FakePlanStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verifies that if Groq returns 429 during /voice synthesis, fallback to TTS.ai delivers WAV."""
    from app.ai.tts import FallbackTTSClient, GroqTTSClient, TTSAiClient, TTSResponseError

    class FailingGroqClient(GroqTTSClient):
        def synthesize(self, text: str, **kwargs: Any) -> bytes:
            raise TTSResponseError(429, "Rate limit exceeded", provider="groq")

    class SuccessfulTTSAiClient(TTSAiClient):
        def synthesize(self, text: str, **kwargs: Any) -> bytes:
            return _make_wav_bytes(duration_seconds=0.5)

    fallback_client = FallbackTTSClient(
        primary=FailingGroqClient(),
        fallback=SuccessfulTTSAiClient(),
    )
    client.app.dependency_overrides[get_tts_client] = lambda: fallback_client
    client.app.dependency_overrides[get_stt_client] = lambda: FakeSTTClient(transcript="Swim tomorrow 6 PM")

    payload = _valid_create_plan(title="Swimming")
    monkeypatch.setattr("app.api.voice.parse_text", lambda **kwargs: ParsedPlan(payload))

    headers = dict(_auth_headers())
    headers["Accept"] = "audio/wav, application/json"

    response = client.post(
        "/voice",
        files={"audio": ("voice.wav", _make_wav_bytes(), "audio/wav")},
        headers=headers,
    )

    assert response.status_code == 201
    assert response.headers["Content-Type"] == "audio/wav"
    assert response.headers["X-Intent"] == "propose_plan"
    assert response.content.startswith(b"RIFF")
    # Plan must NOT be created yet before button confirmation
    assert len(fake_store.created_plans) == 0


def test_voice_multi_turn_exact_flow_study_math_tomorrow_at_2_then_2_am(
    client: TestClient, fake_store: FakePlanStore
) -> None:
    """Verifies the exact multi-turn voice flow over /voice:
    1. 'I want to study math tomorrow at 2 for 1 hour.' -> Assistant asks 'Do you mean 2 AM or 2 PM?'
    2. '2 AM.' with X-Conversation-Id -> Assistant proposes plan retaining tomorrow, study math, and 1 hour.
    3. Accept proposal -> Plan created in store.
    """
    from urllib.parse import unquote
    from app.services.conversation import get_conversation_engine

    engine = get_conversation_engine()
    engine.clear_active_session_for_user(USER_ID)

    # Turn 1: Initial ambiguous utterance
    stt = FakeSTTClient(transcript="I want to study math tomorrow at 2 for 1 hour.")
    tts = FakeTTSClient()
    client.app.dependency_overrides[get_stt_client] = lambda: stt
    client.app.dependency_overrides[get_tts_client] = lambda: tts
    client.app.dependency_overrides.pop(get_llm_client, None)

    headers = dict(_auth_headers())
    headers["Accept"] = "audio/wav, application/json"

    turn1_resp = client.post(
        "/voice",
        files={"audio": ("sample.wav", _make_wav_bytes(), "audio/wav")},
        data={"current_date": "2026-10-28", "timezone": USER_TZ},
        headers=headers,
    )

    assert turn1_resp.status_code == 200
    assert turn1_resp.headers["X-Intent"] == "clarify"
    assert unquote(turn1_resp.headers["X-Reply-Text"]) == "Do you mean 2 AM or 2 PM?"
    conv_id = turn1_resp.headers.get("X-Conversation-Id")
    assert conv_id is not None
    assert len(conv_id) > 0
    # No proposal or plan created yet
    assert len(fake_store.created_plans) == 0

    # Turn 2: User responds "2 AM." with X-Conversation-Id header preserved (as ESP32 does)
    stt.transcript = "2 AM."
    headers["X-Conversation-Id"] = conv_id

    turn2_resp = client.post(
        "/voice",
        files={"audio": ("sample2.wav", _make_wav_bytes(), "audio/wav")},
        data={"current_date": "2026-10-28", "timezone": USER_TZ},
        headers=headers,
    )

    assert turn2_resp.status_code == 201
    assert turn2_resp.headers["X-Intent"] == "propose_plan"
    assert turn2_resp.headers["X-Needs-Button"] == "true"
    assert turn2_resp.headers["X-Conversation-Id"] == conv_id
    proposal_id = turn2_resp.headers.get("X-Proposal-Id")
    assert proposal_id is not None

    # Proposal must retain activity (study math), date (tomorrow: 2026-10-29), time (02:00), duration (60)
    proposal = fake_store.get_latest_pending_proposal(user_id=USER_ID)
    assert proposal is not None
    assert proposal["id"] == proposal_id
    assert "study math" in proposal["title"].lower()
    assert "2026-10-29T02:00" in proposal["planned_start"]
    assert proposal["duration_minutes"] == 60

    # Turn 3: Accept proposal
    accept_resp = client.post(
        f"/plans/proposals/accept?proposal_id={proposal_id}",
        headers=headers,
    )
    assert accept_resp.status_code == 200
    assert len(fake_store.created_plans) == 1
    created = fake_store.created_plans[0]
    assert "study math" in created["title"].lower()


def test_voice_multi_turn_duration_clarification_followed_by_thirty(
    client: TestClient, fake_store: FakePlanStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verifies duration clarification followed by 'Thirty' over /voice."""
    from urllib.parse import unquote
    from app.services.conversation import get_conversation_engine

    engine = get_conversation_engine()
    engine.clear_active_session_for_user(USER_ID)

    stt = FakeSTTClient(transcript="I want to study math tomorrow at 2 PM.")
    tts = FakeTTSClient()
    client.app.dependency_overrides[get_stt_client] = lambda: stt
    client.app.dependency_overrides[get_tts_client] = lambda: tts

    clarify_duration_payload = {
        "intent": "clarify",
        "title": "Study math",
        "category": "study",
        "date": "2026-10-29",
        "time": "14:00",
        "duration_minutes": None,
        "recurrence": None,
        "language": "en",
        "needs_weather_check": False,
        "clarification_question": "How long would you like to schedule this for?",
        "confidence": 0.85,
    }
    monkeypatch.setattr("app.api.voice.parse_text", lambda **kwargs: ParsedPlan(clarify_duration_payload))

    headers = dict(_auth_headers())
    headers["Accept"] = "audio/wav, application/json"

    turn1_resp = client.post(
        "/voice",
        files={"audio": ("sample.wav", _make_wav_bytes(), "audio/wav")},
        data={"current_date": "2026-10-28", "timezone": USER_TZ},
        headers=headers,
    )

    assert turn1_resp.status_code == 200
    assert turn1_resp.headers["X-Intent"] == "clarify"
    reply_text = unquote(turn1_resp.headers["X-Reply-Text"]).lower()
    assert "how long" in reply_text or "duration" in reply_text or "minutes" in reply_text
    conv_id = turn1_resp.headers.get("X-Conversation-Id")
    assert conv_id is not None

    # Turn 2: User responds "Thirty" with X-Conversation-Id
    stt.transcript = "Thirty"
    headers["X-Conversation-Id"] = conv_id

    turn2_resp = client.post(
        "/voice",
        files={"audio": ("sample2.wav", _make_wav_bytes(), "audio/wav")},
        data={"current_date": "2026-10-28", "timezone": USER_TZ},
        headers=headers,
    )

    assert turn2_resp.status_code == 201
    assert turn2_resp.headers["X-Intent"] == "propose_plan"
    proposal = fake_store.get_latest_pending_proposal(user_id=USER_ID)
    assert proposal is not None
    assert proposal["duration_minutes"] == 30
    assert "2026-10-29T14:00" in proposal["planned_start"]


def test_voice_new_conversation_does_not_inherit_old_pending_plan(
    client: TestClient, fake_store: FakePlanStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verifies that a genuinely new voice request without X-Conversation-Id does not inherit old pending state."""
    from app.services.conversation import get_conversation_engine

    engine = get_conversation_engine()
    engine.clear_active_session_for_user(USER_ID)

    stt = FakeSTTClient(transcript="I want to study math tomorrow at 2 for 1 hour.")
    tts = FakeTTSClient()
    client.app.dependency_overrides[get_stt_client] = lambda: stt
    client.app.dependency_overrides[get_tts_client] = lambda: tts

    headers = dict(_auth_headers())
    headers["Accept"] = "audio/wav, application/json"

    turn1_resp = client.post(
        "/voice",
        files={"audio": ("sample.wav", _make_wav_bytes(), "audio/wav")},
        data={"current_date": "2026-10-28", "timezone": USER_TZ},
        headers=headers,
    )
    assert turn1_resp.status_code == 200
    assert turn1_resp.headers["X-Intent"] == "clarify"

    # User starts a completely fresh conversation without X-Conversation-Id header
    stt.transcript = "I want to go swimming tomorrow at 6 PM for two hours."
    headers.pop("X-Conversation-Id", None)

    swimming_payload = {
        "intent": "create_plan",
        "title": "Swimming",
        "category": "sport",
        "date": "2026-10-29",
        "time": "18:00",
        "duration_minutes": 120,
        "recurrence": None,
        "language": "en",
        "needs_weather_check": False,
        "clarification_question": None,
        "confidence": 0.95,
    }
    monkeypatch.setattr("app.api.voice.parse_text", lambda **kwargs: ParsedPlan(swimming_payload))

    turn2_resp = client.post(
        "/voice",
        files={"audio": ("sample2.wav", _make_wav_bytes(), "audio/wav")},
        data={"current_date": "2026-10-28", "timezone": USER_TZ},
        headers=headers,
    )

    assert turn2_resp.status_code == 201
    proposal = fake_store.get_latest_pending_proposal(user_id=USER_ID)
    assert proposal is not None
    assert "swimming" in proposal["title"].lower()
    assert proposal["duration_minutes"] == 120
    assert "2026-10-29T18:00" in proposal["planned_start"]

