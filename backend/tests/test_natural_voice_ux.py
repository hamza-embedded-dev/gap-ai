from __future__ import annotations

import io
from typing import Any
import wave
from unittest.mock import MagicMock

import pytest
from starlette.testclient import TestClient

from app.ai.llm import get_llm_client
from app.ai.stt import get_stt_client
from app.ai.tts import get_tts_client
from app.api.plans import current_user
from app.config import get_settings
from app.db.plans import AuthenticatedUser, PlanStore, get_plan_store
from app.main import app
from app.schemas.conversation import ConversationState
from app.services.conversation import ConversationEngine, get_conversation_engine
from app.services.greetings import (
    check_standalone_greeting,
    get_deterministic_greeting,
    get_deterministic_greeting_for_text,
    is_standalone_greeting,
)

FAKE_USER = AuthenticatedUser(
    id="user-natural-voice-123",
    timezone="Europe/Istanbul",
    is_demo=False,
    demo_expires_at=None,
)


def _make_dummy_wav(duration_seconds: float = 0.5, sample_rate: int = 16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        num_frames = int(duration_seconds * sample_rate)
        wf.writeframes(b"\x00\x00" * num_frames)
    return buf.getvalue()


class MockSTT:
    def __init__(self, transcript: str = "Hi, Coach.") -> None:
        self.transcript = transcript
        self.called_count = 0

    def validate_wav_audio(self, audio_bytes: bytes, max_seconds: float = 10.0) -> bytes:
        return audio_bytes

    def transcribe(self, audio_bytes: bytes, language: str = "en", validate_audio: bool = False) -> str:
        self.called_count += 1
        return self.transcript


class MockTTS:
    def __init__(self) -> None:
        self.synthesize_calls: list[dict[str, Any]] = []

    def synthesize(self, text: str, voice: str | None = None) -> bytes:
        self.synthesize_calls.append({"text": text, "voice": voice})
        return _make_dummy_wav(0.2)


class InMemoryTestPlanStore:
    def __init__(self) -> None:
        self.proposals: dict[str, dict[str, Any]] = {}
        self.plans: list[dict[str, Any]] = []

    def create_plan_proposal(self, user_id: str, proposal: dict[str, Any], conversation_id: str | None = None) -> dict[str, Any]:
        prop = dict(proposal)
        prop["id"] = "prop-123"
        prop["user_id"] = user_id
        prop["conversation_id"] = conversation_id
        self.proposals["prop-123"] = prop
        return prop

    def get_plan_proposal(self, user_id: str, proposal_id: str) -> dict[str, Any] | None:
        return self.proposals.get(proposal_id)

    def create_plan(self, plan: dict[str, Any]) -> dict[str, Any]:
        p = dict(plan)
        p["id"] = f"plan-{len(self.plans) + 1}"
        self.plans.append(p)
        return p


@pytest.fixture
def test_setup():
    store = InMemoryTestPlanStore()
    engine = ConversationEngine()
    mock_llm = MagicMock()
    mock_stt = MockSTT("Hi, Coach.")
    mock_tts = MockTTS()

    app.dependency_overrides[current_user] = lambda: FAKE_USER
    app.dependency_overrides[get_plan_store] = lambda: store
    app.dependency_overrides[get_conversation_engine] = lambda: engine
    app.dependency_overrides[get_llm_client] = lambda: mock_llm
    app.dependency_overrides[get_stt_client] = lambda: mock_stt
    app.dependency_overrides[get_tts_client] = lambda: mock_tts

    client = TestClient(app)
    try:
        yield {
            "client": client,
            "mock_llm": mock_llm,
            "mock_stt": mock_stt,
            "mock_tts": mock_tts,
            "store": store,
            "engine": engine,
        }
    finally:
        app.dependency_overrides.clear()


# =============================================================================
# 1. Standalone vs Actionable Greeting Tests
# =============================================================================


def test_standalone_greeting_recognition():
    # English Standalone Greetings
    assert is_standalone_greeting("Hi, Coach.") is True
    assert is_standalone_greeting("Hello Coach") is True
    assert is_standalone_greeting("Hello") is True
    assert is_standalone_greeting("Hey, Coach") is True
    assert is_standalone_greeting("Good morning, Coach.") is True
    assert is_standalone_greeting("Hi assistant") is True
    assert is_standalone_greeting("Hi") is True

    # Turkish Standalone Greetings
    assert is_standalone_greeting("Merhaba Koç") is True
    assert is_standalone_greeting("Selam Koç") is True
    assert is_standalone_greeting("Günaydın Koç") is True
    assert is_standalone_greeting("Merhaba") is True
    assert is_standalone_greeting("Selam") is True


def test_actionable_requests_not_intercepted_by_greeting():
    # Greetings followed by actionable requests must NOT be treated as standalone greetings
    assert is_standalone_greeting("Hi Coach, can you recommend an activity?") is False
    assert is_standalone_greeting("Hello, I want to go for a walk at 6 PM") is False
    assert is_standalone_greeting("Hey Coach, what should I work on today?") is False
    assert is_standalone_greeting("Hi, let's create a plan for tomorrow") is False
    assert is_standalone_greeting("Do I have pending plans?") is False
    assert is_standalone_greeting("Confirm") is False
    assert is_standalone_greeting("Cancel") is False
    assert is_standalone_greeting("Merhaba Koç, bana bir yürüyüş planı yap") is False


# =============================================================================
# 2. Coach Mode vs Plan Mode Immediate Greetings & Voice Selection
# =============================================================================


def test_coach_mode_standalone_greeting_uses_male_voice_and_bypasses_llm(test_setup):
    client = test_setup["client"]
    mock_llm = test_setup["mock_llm"]
    mock_stt = test_setup["mock_stt"]
    mock_tts = test_setup["mock_tts"]

    mock_stt.transcript = "Hi, Coach."

    wav_payload = _make_dummy_wav()
    response = client.post(
        "/voice",
        files={"audio": ("voice.wav", wav_payload, "audio/wav")},
        data={"mode": "coach"},
        headers={"Accept": "audio/wav", "Authorization": "Bearer fake-token"},
    )

    assert response.status_code == 200
    assert response.headers["Content-Type"] == "audio/wav"
    assert response.headers["X-Intent"] == "greeting"
    assert response.headers["X-Device-Mode"] == "coach"
    assert response.headers["X-LLM-Bypassed"] == "true"
    assert "X-STT-Duration-Ms" in response.headers
    assert "X-TTS-Duration-Ms" in response.headers
    assert "X-Total-Duration-Ms" in response.headers
    assert response.headers["X-Reply-Text"] == "Hi%21%20How%20can%20I%20help%20you%20today%3F"

    # Verify LLM was NEVER called
    mock_llm.generate_json.assert_not_called()
    mock_llm.generate_text.assert_not_called()

    # Verify Coach voice used (male voice: troy / am_adam)
    settings = get_settings()
    expected_coach_voice = settings.tts_coach_voice
    assert any(c["voice"] == expected_coach_voice for c in mock_tts.synthesize_calls)


def test_plan_mode_standalone_greeting_uses_female_voice_and_bypasses_llm(test_setup):
    client = test_setup["client"]
    mock_llm = test_setup["mock_llm"]
    mock_stt = test_setup["mock_stt"]
    mock_tts = test_setup["mock_tts"]

    mock_stt.transcript = "Hello."

    wav_payload = _make_dummy_wav()
    response = client.post(
        "/voice",
        files={"audio": ("voice.wav", wav_payload, "audio/wav")},
        data={"mode": "plan"},
        headers={"Accept": "audio/wav", "Authorization": "Bearer fake-token"},
    )

    assert response.status_code == 200
    assert response.headers["Content-Type"] == "audio/wav"
    assert response.headers["X-Intent"] == "greeting"
    assert response.headers["X-Device-Mode"] == "plan"
    assert response.headers["X-LLM-Bypassed"] == "true"
    assert response.headers["X-Reply-Text"] == "Hi%21%20Would%20you%20like%20to%20create%20a%20plan%3F"

    # Verify LLM was NEVER called
    mock_llm.generate_json.assert_not_called()
    mock_llm.generate_text.assert_not_called()

    # Verify Plan voice used (female voice: autumn / af_heart)
    settings = get_settings()
    expected_plan_voice = settings.tts_voice
    assert any(c["voice"] == expected_plan_voice for c in mock_tts.synthesize_calls)


def test_turkish_standalone_greeting_deterministic_response(test_setup):
    client = test_setup["client"]
    mock_llm = test_setup["mock_llm"]
    mock_stt = test_setup["mock_stt"]

    mock_stt.transcript = "Merhaba Koç"

    wav_payload = _make_dummy_wav()
    response = client.post(
        "/voice",
        files={"audio": ("voice.wav", wav_payload, "audio/wav")},
        data={"mode": "coach"},
        headers={"Accept": "audio/wav", "Authorization": "Bearer fake-token"},
    )

    assert response.status_code == 200
    assert response.headers["X-Intent"] == "greeting"
    assert response.headers["X-LLM-Bypassed"] == "true"
    # Merhaba! Bugün senin için ne yapabilirim?
    assert "Merhaba" in response.headers["X-Reply-Text"]

    # Verify LLM was NEVER called
    mock_llm.generate_json.assert_not_called()


# =============================================================================
# 3. Actionable Requests Continue Without Greeting Interception
# =============================================================================


def test_greeting_plus_actionable_request_continues_to_flow(test_setup):
    client = test_setup["client"]
    mock_llm = test_setup["mock_llm"]
    mock_stt = test_setup["mock_stt"]

    # "Hi Coach, can you recommend an activity?" in coach mode
    mock_stt.transcript = "Hi Coach, can you recommend an activity?"

    wav_payload = _make_dummy_wav()
    response = client.post(
        "/voice",
        files={"audio": ("voice.wav", wav_payload, "audio/wav")},
        data={"mode": "coach"},
        headers={"Accept": "audio/wav", "Authorization": "Bearer fake-token"},
    )

    assert response.status_code == 200
    # Must NOT be intercepted as a greeting
    assert response.headers["X-Intent"] == "coach_recommendation"


def test_greeting_while_proposal_pending_preserves_proposal(test_setup):
    client = test_setup["client"]
    mock_stt = test_setup["mock_stt"]
    engine = test_setup["engine"]

    from app.services.conversation import ConversationSession
    cid = "conv-pending-123"
    session = ConversationSession(id=cid, user_id=FAKE_USER.id)
    session.state = ConversationState.AWAITING_CONFIRMATION
    session.proposal_id = "prop-pending-999"
    session.pending_plan.title = "Evening Walk"
    session.pending_plan.date = "2026-10-29"
    session.pending_plan.time = "18:00"
    engine._sessions[cid] = session
    engine._user_active_sessions[FAKE_USER.id] = cid

    mock_stt.transcript = "Hi, Coach."

    wav_payload = _make_dummy_wav()
    response = client.post(
        "/voice",
        files={"audio": ("voice.wav", wav_payload, "audio/wav")},
        data={"mode": "coach", "conversation_id": session.id},
        headers={"Accept": "audio/wav", "Authorization": "Bearer fake-token"},
    )

    assert response.status_code == 200
    assert response.headers["X-Intent"] == "greeting"
    # Crucial: pending proposal must remain preserved
    assert response.headers["X-Proposal-Id"] == "prop-pending-999"
    assert response.headers["X-Needs-Button"] == "true"
    assert session.state == ConversationState.AWAITING_CONFIRMATION


def test_greeting_never_creates_plans_in_database(test_setup):
    client = test_setup["client"]
    store = test_setup["store"]
    mock_stt = test_setup["mock_stt"]

    mock_stt.transcript = "Hello."

    wav_payload = _make_dummy_wav()
    client.post(
        "/voice",
        files={"audio": ("voice.wav", wav_payload, "audio/wav")},
        data={"mode": "plan"},
        headers={"Accept": "audio/wav", "Authorization": "Bearer fake-token"},
    )

    # Database must have 0 created plans
    assert len(store.plans) == 0


# =============================================================================
# 4. Latency Optimization & Audio Cache Tests
# =============================================================================


def test_greeting_audio_cache_eliminates_synthesis_time(test_setup):
    client = test_setup["client"]
    mock_stt = test_setup["mock_stt"]
    mock_tts = test_setup["mock_tts"]

    mock_stt.transcript = "Hi, Coach."
    wav_payload = _make_dummy_wav()

    # First greeting call: synthesizes and populates cache
    r1 = client.post(
        "/voice",
        files={"audio": ("voice.wav", wav_payload, "audio/wav")},
        data={"mode": "coach"},
        headers={"Accept": "audio/wav", "Authorization": "Bearer fake-token"},
    )
    assert r1.status_code == 200
    initial_tts_calls = len(mock_tts.synthesize_calls)

    # Second greeting call: should be served from memory cache (no new synthesis call)
    r2 = client.post(
        "/voice",
        files={"audio": ("voice.wav", wav_payload, "audio/wav")},
        data={"mode": "coach"},
        headers={"Accept": "audio/wav", "Authorization": "Bearer fake-token"},
    )
    assert r2.status_code == 200
    # Calls to synthesize did not increase
    assert len(mock_tts.synthesize_calls) == initial_tts_calls
    # Duration reported in headers is sub-millisecond (< 1.0 ms)
    tts_ms = float(r2.headers["X-TTS-Duration-Ms"])
    assert tts_ms < 1.0


def test_mode_announcement_concise_and_cached():
    client = TestClient(app)
    mock_tts = MockTTS()
    app.dependency_overrides[get_tts_client] = lambda: mock_tts

    # Coach Mode announcement
    r_coach = client.get("/voice/mode-announcement?mode=coach")
    assert r_coach.status_code == 200
    assert r_coach.headers["X-Reply-Text"] == "Coach%20Mode%20active."

    # Plan Mode announcement
    r_plan = client.get("/voice/mode-announcement?mode=plan")
    assert r_plan.status_code == 200
    assert r_plan.headers["X-Reply-Text"] == "Plan%20Mode%20active."

    # Verify cached on second call
    call_count = len(mock_tts.synthesize_calls)
    client.get("/voice/mode-announcement?mode=coach")
    assert len(mock_tts.synthesize_calls) == call_count
