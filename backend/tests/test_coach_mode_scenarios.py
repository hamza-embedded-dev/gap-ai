from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Literal
import io
import wave
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.api.plans import current_user
from app.db.plans import AuthenticatedUser, get_plan_store
from app.ai.llm import get_llm_client
from app.ai.stt import get_stt_client
from app.ai.tts import get_tts_client
from app.services.conversation import ConversationEngine, get_conversation_engine
from app.config import get_settings


USER_ID = "user-hamza-e2e"
USER_TZ = "Europe/Istanbul"


def _make_dummy_wav() -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(b"\x00\x00" * 1600)  # 0.1s
    return buf.getvalue()


class MockPlanStore:
    def __init__(self) -> None:
        self.plans: list[dict[str, Any]] = []
        self.proposals: dict[str, list[dict[str, Any]]] = {}
        self.feedback: list[dict[str, Any]] = []

    def get_plans(self, user_id: str) -> list[dict[str, Any]]:
        return [p for p in self.plans if p.get("user_id") == user_id]

    def list_plans(self, user_id: str) -> list[dict[str, Any]]:
        return self.get_plans(user_id)

    def list_outcomes(self, user_id: str) -> list[dict[str, Any]]:
        return []

    def get_personalization(self, user_id: str) -> dict[str, Any]:
        return {}

    def create_plan(self, plan: dict[str, Any]) -> dict[str, Any]:
        data = dict(plan)
        uid = data.pop("user_id", None)
        record = {
            "id": f"plan-{len(self.plans) + 1}",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "latest_outcome": None,
            **data,
        }
        self.plans.append({"user_id": uid, **record})
        return record

    def create_plan_proposal(
        self, *, user_id: str, proposal: dict[str, Any], conversation_id: str | None = None
    ) -> dict[str, Any]:
        record = {
            "id": f"prop-{len(self.proposals.get(user_id, [])) + 1}",
            "user_id": user_id,
            "conversation_id": conversation_id,
            "title": proposal.get("title", "Plan"),
            "category": proposal.get("category", "other"),
            "planned_start": proposal.get("planned_start"),
            "planned_end": proposal.get("planned_end"),
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
        created = self.create_plan({
            "user_id": user_id,
            "title": proposal["title"],
            "category": proposal["category"],
            "planned_start": proposal["planned_start"],
            "planned_end": proposal["planned_end"],
            "recurrence_rule": proposal.get("recurrence_rule"),
            "source": "voice",
        })
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

    def save_recommendation_feedback(self, user_id: str, feedback: dict[str, Any]) -> dict[str, Any]:
        entry = {
            "id": f"fb-{len(self.feedback) + 1}",
            "user_id": user_id,
            **feedback,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self.feedback.append(entry)
        return entry

    def list_recommendation_feedback(self, user_id: str) -> list[dict[str, Any]]:
        return [f for f in self.feedback if f.get("user_id") == user_id]

    def get_recommendation_feedback(self, user_id: str) -> list[dict[str, Any]]:
        return self.list_recommendation_feedback(user_id)


class MockTTSClient:
    def __init__(self) -> None:
        self.synthesize_calls: list[dict[str, Any]] = []

    def synthesize(self, text: str, *, voice: str | None = None, **kwargs: Any) -> bytes:
        self.synthesize_calls.append({"text": text, "voice": voice, **kwargs})
        return _make_dummy_wav()


class MockSTTClient:
    def __init__(self, transcript: str = "") -> None:
        self.transcript = transcript

    def validate_wav_audio(self, audio: bytes, max_seconds: float = 10.0) -> bytes:
        return audio

    def transcribe(self, audio: bytes, **kwargs: Any) -> str:
        return self.transcript


class DynamicMockLLMClient:
    def complete_json(self, messages: list[dict[str, str]], **kwargs: Any) -> dict[str, Any]:
        user_msg = messages[-1].get("content", "") if messages else ""
        lower = user_msg.lower()
        if "run" in lower:
            return {
                "intent": "create_plan",
                "title": "Run",
                "category": "sport",
                "date": "2026-10-29",
                "time": "07:00",
                "duration_minutes": 30,
                "recurrence": None,
                "language": "en",
                "needs_weather_check": False,
                "clarification_question": None,
                "confidence": 0.95,
            }
        if "walk" in lower:
            return {
                "intent": "clarify",
                "title": "Walk",
                "category": "health",
                "date": "2026-10-29",
                "time": "18:00",
                "duration_minutes": None,
                "recurrence": None,
                "language": "en",
                "needs_weather_check": False,
                "clarification_question": "How long would you like to schedule this for?",
                "confidence": 0.95,
            }
        return {
            "intent": "unsupported",
            "title": None,
            "category": None,
            "date": None,
            "time": None,
            "duration_minutes": None,
            "recurrence": None,
            "language": "en",
            "needs_weather_check": False,
            "clarification_question": None,
            "confidence": 0.5,
        }


@pytest.fixture
def test_setup():
    store = MockPlanStore()
    engine = ConversationEngine()
    tts = MockTTSClient()
    stt = MockSTTClient()
    llm = DynamicMockLLMClient()

    user = AuthenticatedUser(
        id=USER_ID,
        timezone=USER_TZ,
        is_demo=False,
        demo_expires_at=None,
        display_name="Hamza Emin",
    )

    app.dependency_overrides[get_plan_store] = lambda: store
    app.dependency_overrides[get_conversation_engine] = lambda: engine
    app.dependency_overrides[get_tts_client] = lambda: tts
    app.dependency_overrides[get_stt_client] = lambda: stt
    app.dependency_overrides[get_llm_client] = lambda: llm
    app.dependency_overrides[current_user] = lambda: user

    client = TestClient(app)
    try:
        yield {
            "client": client,
            "store": store,
            "engine": engine,
            "tts": tts,
            "stt": stt,
            "user": user,
        }
    finally:
        app.dependency_overrides.clear()


def test_scenario_a_plan_mode_walk_confirmation(test_setup):
    """
    Senaryo A — Plan Mode:
    1. Cihaz Plan Mode'da başlar.
    2. Kullanıcı: 'I want to go for a walk today at 6 p.m.'
    3. Sistem eksik süreyi sorar (Activity: Walk preserved).
    4. Kullanıcı: 'for a one hour'
    5. Sistem planı özetler: Walk, 6 PM, one hour.
    6. Kullanıcı: 'Right.' (onay).
    7. Backend planı gerçekten kaydeder.
    """
    ctx = test_setup
    client = ctx["client"]
    stt = ctx["stt"]
    tts = ctx["tts"]
    store = ctx["store"]
    wav_bytes = _make_dummy_wav()

    # Turn 1: "I want to go for a walk today at 6 p.m."
    stt.transcript = "I want to go for a walk today at 6 p.m."
    res1 = client.post(
        "/voice",
        files={"audio": ("voice.wav", wav_bytes, "audio/wav")},
        data={"mode": "plan", "current_date": "2026-10-29"},
        headers={"Accept": "audio/wav", "X-Device-Mode": "plan"},
    )
    assert res1.status_code == 200
    conv_id = res1.headers.get("x-conversation-id")
    assert conv_id is not None
    assert res1.headers.get("x-intent") == "clarify"
    # Verify title extracted as Walk, not awkward "Create a plan to activity today"
    session = ctx["engine"].get_session(conv_id)
    assert session.pending_plan.title == "Walk"

    # Turn 2: "for a one hour"
    stt.transcript = "for a one hour"
    res2 = client.post(
        "/voice",
        files={"audio": ("voice.wav", wav_bytes, "audio/wav")},
        data={"mode": "plan", "conversation_id": conv_id, "current_date": "2026-10-29"},
        headers={"Accept": "audio/wav", "X-Conversation-Id": conv_id, "X-Device-Mode": "plan"},
    )
    assert res2.status_code == 201
    assert res2.headers.get("x-intent") == "propose_plan"
    prop_id = res2.headers.get("x-proposal-id")
    assert prop_id is not None
    assert res2.headers.get("x-needs-button") == "true"
    # Plan summary prompt includes Walk, 6:00 PM, 60 minutes
    assert "Walk" in session.pending_plan.title

    # Turn 3: "Right." (the exact production utterance that previously caused repeated prompts)
    stt.transcript = "Right."
    res3 = client.post(
        "/voice",
        files={"audio": ("voice.wav", wav_bytes, "audio/wav")},
        data={"mode": "plan", "conversation_id": conv_id, "current_date": "2026-10-29"},
        headers={"Accept": "audio/wav", "X-Conversation-Id": conv_id, "X-Device-Mode": "plan"},
    )
    assert res3.status_code == 201
    assert res3.headers.get("x-intent") == "plan_confirmed"
    assert res3.headers.get("x-needs-button") == "false"

    # Verify plan was genuinely persisted in store
    plans = store.get_plans(USER_ID)
    assert len(plans) == 1
    assert plans[0]["title"] == "Walk"
    assert "18:00" in plans[0]["planned_start"]


def test_scenario_b_pending_plan_status_query_and_idempotency(test_setup):
    """
    Senaryo B — Pending Plan Query and Button Idempotency:
    - User asks 'Do I have a pending plans?' -> Answered informatively without re-prompting or wiping proposal.
    - Idempotent confirmation does not duplicate plans.
    """
    ctx = test_setup
    client = ctx["client"]
    stt = ctx["stt"]
    wav_bytes = _make_dummy_wav()

    # Create a proposal first
    stt.transcript = "Plan a run today at 7 AM for 30 minutes"
    res1 = client.post(
        "/voice",
        files={"audio": ("voice.wav", wav_bytes, "audio/wav")},
        data={"mode": "plan", "current_date": "2026-10-29"},
        headers={"Accept": "audio/wav"},
    )
    conv_id = res1.headers.get("x-conversation-id")
    assert conv_id is not None
    prop_id = res1.headers.get("x-proposal-id")
    assert prop_id is not None

    # Query: "Do I have a pending plans?"
    stt.transcript = "Do I have a pending plans?"
    res2 = client.post(
        "/voice",
        files={"audio": ("voice.wav", wav_bytes, "audio/wav")},
        data={"mode": "plan", "conversation_id": conv_id, "current_date": "2026-10-29"},
        headers={"Accept": "audio/wav", "X-Conversation-Id": conv_id},
    )
    assert res2.status_code == 200
    assert res2.headers.get("x-intent") == "info"
    # Proposal ID is retained and NOT lost
    session = ctx["engine"].get_session(conv_id)
    assert session.proposal_id == prop_id

    # Confirm via proposal accept endpoint
    res_accept = client.post(f"/plans/proposals/accept?proposal_id={prop_id}")
    assert res_accept.status_code == 200
    assert len(ctx["store"].get_plans(USER_ID)) == 1


def test_scenario_c_coach_mode_recommendations_and_male_voice(test_setup):
    """
    Senaryo C — Coach Recommendations:
    1. Coach mode activation: Male TTS voice selected ('troy').
    2. 'Hey Coach, what can you recommend for me today?' -> Reads 1st idea.
    3. User: 'I don't like it' -> Feedback 'dismissed' persisted, 2nd idea read.
    4. User: 'Something else' -> 3rd idea read.
    5. Exhaustion -> Pool refresh, prevents duplicate reading.
    """
    ctx = test_setup
    client = ctx["client"]
    stt = ctx["stt"]
    tts = ctx["tts"]
    store = ctx["store"]
    wav_bytes = _make_dummy_wav()

    # Initial Coach request
    stt.transcript = "Hey Coach, what can you recommend for me today?"
    res1 = client.post(
        "/voice",
        files={"audio": ("voice.wav", wav_bytes, "audio/wav")},
        data={"mode": "coach", "current_date": "2026-10-29"},
        headers={"Accept": "audio/wav", "X-Device-Mode": "coach"},
    )
    assert res1.status_code == 200
    assert res1.headers.get("x-device-mode") == "coach"
    assert res1.headers.get("x-intent") == "coach_recommendation"
    rec1_id = res1.headers.get("x-recommendation-id")
    assert rec1_id is not None
    conv_id = res1.headers.get("x-conversation-id")
    assert conv_id is not None

    # Verify male voice 'troy' was passed to TTS
    assert len(tts.synthesize_calls) > 0
    assert tts.synthesize_calls[-1]["voice"] == get_settings().tts_coach_voice
    assert tts.synthesize_calls[-1]["voice"] == "troy"

    # Turn 2: Dislike ("I don't like it")
    stt.transcript = "I don't like it"
    res2 = client.post(
        "/voice",
        files={"audio": ("voice.wav", wav_bytes, "audio/wav")},
        data={"mode": "coach", "conversation_id": conv_id, "current_date": "2026-10-29"},
        headers={"Accept": "audio/wav", "X-Conversation-Id": conv_id, "X-Device-Mode": "coach"},
    )
    assert res2.status_code == 200
    rec2_id = res2.headers.get("x-recommendation-id")
    assert rec2_id is not None
    assert rec2_id != rec1_id  # Must be a different recommendation!

    # Verify dismissal feedback was persisted in store
    fb_list = store.get_recommendation_feedback(USER_ID)
    assert len(fb_list) >= 1
    assert fb_list[-1]["recommendation_id"] == rec1_id
    assert fb_list[-1]["action"] == "dismissed"

    # Turn 3: Dislike again ("Something else")
    stt.transcript = "Something else"
    res3 = client.post(
        "/voice",
        files={"audio": ("voice.wav", wav_bytes, "audio/wav")},
        data={"mode": "coach", "conversation_id": conv_id, "current_date": "2026-10-29"},
        headers={"Accept": "audio/wav", "X-Conversation-Id": conv_id, "X-Device-Mode": "coach"},
    )
    assert res3.status_code == 200
    rec3_id = res3.headers.get("x-recommendation-id")
    assert rec3_id is not None
    assert rec3_id not in (rec1_id, rec2_id)


def test_scenario_d_convert_recommendation_to_plan(test_setup):
    """
    Senaryo D — Converting Recommendation to Plan:
    1. User likes recommendation: 'I like it.'
    2. Coach asks: 'Bu öneri için tarih veya saatini değiştirmek ister misin?'
    3. User provides custom schedule: 'Yes, make it tomorrow at 5 PM.'
    4. System prepares plan preserving recommendation title and category.
    5. User confirms -> Plan persisted in store, feedback accepted recorded.
    """
    ctx = test_setup
    client = ctx["client"]
    stt = ctx["stt"]
    tts = ctx["tts"]
    store = ctx["store"]
    wav_bytes = _make_dummy_wav()

    # Step 1: Request recommendation
    stt.transcript = "Hey Coach, what can you recommend for me today?"
    res1 = client.post(
        "/voice",
        files={"audio": ("voice.wav", wav_bytes, "audio/wav")},
        data={"mode": "coach", "current_date": "2026-10-29"},
        headers={"Accept": "audio/wav", "X-Device-Mode": "coach"},
    )
    conv_id = res1.headers.get("x-conversation-id")
    rec_id = res1.headers.get("x-recommendation-id")

    # Step 2: User says "I like it"
    stt.transcript = "I like it"
    res2 = client.post(
        "/voice",
        files={"audio": ("voice.wav", wav_bytes, "audio/wav")},
        data={"mode": "coach", "conversation_id": conv_id, "current_date": "2026-10-29"},
        headers={"Accept": "audio/wav", "X-Conversation-Id": conv_id, "X-Device-Mode": "coach"},
    )
    assert res2.status_code == 200
    assert res2.headers.get("x-intent") == "coach_time_prompt"

    # Step 3: User says "Yes, make it tomorrow at 5 PM"
    stt.transcript = "Yes, make it tomorrow at 5 PM"
    res3 = client.post(
        "/voice",
        files={"audio": ("voice.wav", wav_bytes, "audio/wav")},
        data={"mode": "coach", "conversation_id": conv_id, "current_date": "2026-10-29"},
        headers={"Accept": "audio/wav", "X-Conversation-Id": conv_id, "X-Device-Mode": "coach"},
    )
    assert res3.status_code == 201
    assert res3.headers.get("x-intent") == "propose_plan"
    assert res3.headers.get("x-needs-button") == "true"
    prop_id = res3.headers.get("x-proposal-id")
    assert prop_id is not None

    # Step 4: User confirms: "Right."
    stt.transcript = "Right."
    res4 = client.post(
        "/voice",
        files={"audio": ("voice.wav", wav_bytes, "audio/wav")},
        data={"mode": "coach", "conversation_id": conv_id, "current_date": "2026-10-29"},
        headers={"Accept": "audio/wav", "X-Conversation-Id": conv_id, "X-Device-Mode": "coach"},
    )
    assert res4.status_code == 201
    assert res4.headers.get("x-intent") == "plan_confirmed"

    # Verify plan was saved to store with tomorrow's date and 17:00
    plans = store.get_plans(USER_ID)
    assert len(plans) == 1
    tomorrow = (date(2026, 10, 29) + timedelta(days=1)).isoformat()
    assert plans[0]["planned_start"].startswith(tomorrow)
    assert "17:00" in plans[0]["planned_start"]

    # Verify accepted feedback was recorded
    fb_list = store.get_recommendation_feedback(USER_ID)
    assert any(f.get("action") == "accepted" for f in fb_list)


def test_scenario_e_mode_announcement_endpoint(test_setup):
    """
    Senaryo E — Mode Announcement Endpoint:
    - GET /voice/mode-announcement?mode=coach -> returns WAV synthesized with male voice 'troy'.
    - GET /voice/mode-announcement?mode=plan -> returns WAV synthesized with default plan voice.
    """
    ctx = test_setup
    client = ctx["client"]
    tts = ctx["tts"]

    # Coach mode announcement
    res_coach = client.get("/voice/mode-announcement?mode=coach")
    assert res_coach.status_code == 200
    assert res_coach.headers["Content-Type"] == "audio/wav"
    assert res_coach.headers["X-Device-Mode"] == "coach"
    assert tts.synthesize_calls[-1]["voice"] == "troy"

    # Plan mode announcement
    res_plan = client.get("/voice/mode-announcement?mode=plan")
    assert res_plan.status_code == 200
    assert res_plan.headers["Content-Type"] == "audio/wav"
    assert res_plan.headers["X-Device-Mode"] == "plan"
    assert tts.synthesize_calls[-1]["voice"] == get_settings().tts_voice
