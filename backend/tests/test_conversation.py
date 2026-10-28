from __future__ import annotations

from datetime import date, datetime, timezone
import io
from typing import Any
import uuid
import wave
from urllib.parse import unquote


import pytest
from starlette.testclient import TestClient

from app.ai.llm import get_llm_client
from app.ai.stt import get_stt_client
from app.ai.tts import get_tts_client
from app.api.plans import current_user
from app.db.plans import AuthenticatedUser, PlanStore, get_plan_store
from app.main import app
from app.schemas.conversation import ConversationState
from app.services.conversation import ConversationEngine, get_conversation_engine

PEPPER = "p" * 32
TOKEN = "valid-test-token"
USER_TZ = "Europe/Istanbul"
USER_ID = "user-conv-test-123"
ANCHOR_DATE = "2026-10-28"  # Wednesday


def _make_wav_bytes(duration_seconds: float = 1.0) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        n_frames = int(16000 * duration_seconds)
        w.writeframes(b"\x00" * (n_frames * 2))
    return buf.getvalue()


class InMemoryConversationStore:
    """In-memory PlanStore for testing conversation persistence and idempotency."""

    def __init__(self) -> None:
        self.created_plans: list[dict[str, Any]] = []
        self.proposals: dict[str, list[dict[str, Any]]] = {}
        self.idempotency_records: dict[str, dict[str, Any]] = {}
        self.simulate_persistence_failure: bool = False

    def create_plan(self, plan: dict[str, Any]) -> dict[str, Any]:
        if self.simulate_persistence_failure:
            raise RuntimeError("Simulated database write error")
        record = {
            "id": str(uuid.uuid4()),
            "title": plan["title"],
            "category": plan.get("category", "other"),
            "planned_start": plan["planned_start"],
            "planned_end": plan["planned_end"],
            "recurrence_rule": plan.get("recurrence_rule"),
            "source": plan.get("source", "web"),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "latest_outcome": None,
        }
        self.created_plans.append(record)
        return record

    def create_plan_idempotently(
        self,
        *,
        user_id: str,
        idempotency_key: str,
        request_hash: str,
        plan: dict[str, Any],
    ) -> tuple[dict[str, Any], bool]:
        if self.simulate_persistence_failure:
            raise RuntimeError("Simulated database write error")
        if idempotency_key in self.idempotency_records:
            existing = self.idempotency_records[idempotency_key]
            if existing["hash"] != request_hash:
                return {}, True  # Conflict
            return existing["plan"], False
        created = self.create_plan(plan)
        self.idempotency_records[idempotency_key] = {"hash": request_hash, "plan": created}
        return created, False

    def create_plan_proposal(
        self,
        *,
        user_id: str,
        proposal: dict[str, Any],
        conversation_id: str | None = None,
    ) -> dict[str, Any]:
        record = {
            "id": str(uuid.uuid4()),
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


class DummyTTS:
    def synthesize(self, text: str) -> bytes:
        return _make_wav_bytes(duration_seconds=0.5)


class FakeSTTClient:
    def __init__(self, transcript: str) -> None:
        self.transcript = transcript

    def validate_wav_audio(self, audio: bytes, max_seconds: float = 10.0) -> bytes:
        return audio

    def transcribe(self, audio: bytes, **kwargs: Any) -> str:
        return self.transcript


@pytest.fixture
def auth_user() -> AuthenticatedUser:
    return AuthenticatedUser(
        id=USER_ID,
        timezone=USER_TZ,
        is_demo=False,
        demo_expires_at=None,
        display_name="Hamza Emin",
    )


@pytest.fixture
def store() -> InMemoryConversationStore:
    return InMemoryConversationStore()


@pytest.fixture
def engine() -> ConversationEngine:
    return ConversationEngine()


class DynamicFakeLLMClient:
    def complete_json(self, messages: list[dict[str, str]], **kwargs: Any) -> dict[str, Any]:
        user_msg = ""
        for m in messages:
            if m.get("role") == "user":
                user_msg = m.get("content", "")
        lower = user_msg.lower()

        if any(w in lower for w in ["joke", "weather", "who are you", "what can you do"]):
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
                "confidence": 0.99,
            }

        has_time = any(w in lower for w in ["17:00", "05:00", "20:00", "5 pm", "5 am", "8 pm"])
        time_val = None
        if "17:00" in lower or "5 pm" in lower:
            time_val = "17:00"
        elif "05:00" in lower or "5 am" in lower:
            time_val = "05:00"
        elif "20:00" in lower or "8 pm" in lower:
            time_val = "20:00"

        title = "Study" if "study" in lower else ("Workout" if "workout" in lower or "run" in lower else "Activity")
        category = "study" if "study" in lower else ("sport" if "workout" in lower or "run" in lower else "other")

        dur = 60
        if "two hours" in lower or "2 hours" in lower or "for two hours" in lower:
            dur = 120
        elif "three hours" in lower or "3 hours" in lower:
            dur = 180
        elif "30 minutes" in lower or "half an hour" in lower:
            dur = 30

        plan_date = "2026-10-29"
        if "friday" in lower:
            plan_date = "2026-10-30"

        if not has_time and not time_val:
            return {
                "intent": "clarify",
                "title": title,
                "category": category,
                "date": plan_date,
                "time": None,
                "duration_minutes": dur,
                "recurrence": None,
                "language": "en",
                "needs_weather_check": False,
                "clarification_question": "What time would you like to start?",
                "confidence": 0.85,
            }

        return {
            "intent": "create_plan",
            "title": title,
            "category": category,
            "date": plan_date,
            "time": time_val or "17:00",
            "duration_minutes": dur,
            "recurrence": None,
            "language": "en",
            "needs_weather_check": False,
            "clarification_question": None,
            "confidence": 0.95,
        }


@pytest.fixture
def client(auth_user: AuthenticatedUser, store: InMemoryConversationStore, engine: ConversationEngine) -> TestClient:
    app.dependency_overrides[current_user] = lambda: auth_user
    app.dependency_overrides[get_plan_store] = lambda: store
    app.dependency_overrides[get_conversation_engine] = lambda: engine
    app.dependency_overrides[get_tts_client] = lambda: DummyTTS()
    app.dependency_overrides[get_llm_client] = lambda: DynamicFakeLLMClient()
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


# ==============================================================================
# 16 REQUIRED TEST CASES (Section 7)
# ==============================================================================


def test_1_missing_start_time_triggers_clarification(
    client: TestClient, store: InMemoryConversationStore
) -> None:
    """1. Missing start time triggers clarification question in English."""
    resp = client.post(
        "/conversation",
        json={"text": "I want to study tomorrow.", "current_date": ANCHOR_DATE, "timezone": USER_TZ},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["state"] == "awaiting_clarification"
    assert data["prompt_type"] == "clarification"
    assert "what time" in data["reply_text"].lower()
    # Ensure no plan written to database yet
    assert len(store.created_plans) == 0


def test_2_ambiguous_ampm_triggers_clarification(
    client: TestClient, store: InMemoryConversationStore
) -> None:
    """2. Ambiguous AM/PM (e.g. 'At five') triggers clarification asking 5 AM or 5 PM."""
    # Turn 1: Initial request
    r1 = client.post(
        "/conversation",
        json={"text": "I want to study tomorrow evening.", "current_date": ANCHOR_DATE, "timezone": USER_TZ},
    )
    assert r1.status_code == 200
    cid = r1.json()["conversation_id"]

    # Turn 2: Ambiguous time "At five"
    r2 = client.post(
        "/conversation",
        json={"text": "At five.", "conversation_id": cid, "current_date": ANCHOR_DATE, "timezone": USER_TZ},
    )
    assert r2.status_code == 200
    d2 = r2.json()
    assert d2["state"] == "awaiting_clarification"
    assert "5 AM or 5 PM" in d2["reply_text"]
    assert len(store.created_plans) == 0


def test_3_correct_interpretation_of_5am_and_5pm(
    client: TestClient, store: InMemoryConversationStore
) -> None:
    """3. Correct interpretation of 5 AM (05:00) and 5 PM (17:00)."""
    # 5 PM resolution
    r1 = client.post(
        "/conversation",
        json={"text": "I want to study tomorrow.", "current_date": ANCHOR_DATE, "timezone": USER_TZ},
    )
    cid1 = r1.json()["conversation_id"]
    r2 = client.post(
        "/conversation",
        json={"text": "5 PM", "conversation_id": cid1, "current_date": ANCHOR_DATE, "timezone": USER_TZ},
    )
    assert r2.status_code == 200
    d2 = r2.json()
    assert d2["pending_plan"]["time"] == "17:00"

    # 5 AM resolution
    r3 = client.post(
        "/conversation",
        json={"text": "I want to study tomorrow.", "current_date": ANCHOR_DATE, "timezone": USER_TZ},
    )
    cid2 = r3.json()["conversation_id"]
    r4 = client.post(
        "/conversation",
        json={"text": "5 AM", "conversation_id": cid2, "current_date": ANCHOR_DATE, "timezone": USER_TZ},
    )
    assert r4.status_code == 200
    d4 = r4.json()
    assert d4["pending_plan"]["time"] == "05:00"


def test_4_correct_relative_date_interpretation_in_europe_istanbul(
    client: TestClient
) -> None:
    """4. Correct relative-date interpretation (tomorrow, Friday) in Europe/Istanbul."""
    # ANCHOR_DATE 2026-10-28 is Wednesday
    # Tomorrow is 2026-10-29 (Thursday)
    # Friday is 2026-10-30 (Friday)
    r1 = client.post(
        "/conversation",
        json={"text": "I want to study tomorrow at 5 PM.", "current_date": ANCHOR_DATE, "timezone": USER_TZ},
    )
    assert r1.status_code == 200
    assert r1.json()["pending_plan"]["date"] == "2026-10-29"

    r2 = client.post(
        "/conversation",
        json={"text": "I want to study on Friday at 5 PM.", "current_date": ANCHOR_DATE, "timezone": USER_TZ},
    )
    assert r2.status_code == 200
    assert r2.json()["pending_plan"]["date"] == "2026-10-30"


def test_5_pending_context_survives_multiple_turns(
    client: TestClient, store: InMemoryConversationStore
) -> None:
    """5. Pending context (task, date, duration) survives multiple conversation turns."""
    # Turn 1: "I want to study tomorrow evening."
    r1 = client.post(
        "/conversation",
        json={"text": "I want to study tomorrow evening.", "current_date": ANCHOR_DATE, "timezone": USER_TZ},
    )
    cid = r1.json()["conversation_id"]

    # Turn 2: "At five."
    r2 = client.post(
        "/conversation",
        json={"text": "At five.", "conversation_id": cid, "current_date": ANCHOR_DATE, "timezone": USER_TZ},
    )
    assert r2.status_code == 200

    # Turn 3: "5 PM."
    r3 = client.post(
        "/conversation",
        json={"text": "5 PM.", "conversation_id": cid, "current_date": ANCHOR_DATE, "timezone": USER_TZ},
    )
    d3 = r3.json()
    assert d3["state"] == "awaiting_confirmation"
    # Verify original task and date were retained across all 3 turns
    assert d3["pending_plan"]["title"].lower() == "study"
    assert d3["pending_plan"]["date"] == "2026-10-29"
    assert d3["pending_plan"]["time"] == "17:00"
    assert len(store.created_plans) == 0


def test_6_corrections_to_task_date_time_and_duration(
    client: TestClient
) -> None:
    """6. Corrections to task, date, time, and duration without restarting."""
    r1 = client.post(
        "/conversation",
        json={"text": "I want to study tomorrow at 5 PM.", "current_date": ANCHOR_DATE, "timezone": USER_TZ},
    )
    cid = r1.json()["conversation_id"]

    # Correction A: Time -> "No, I meant 5 AM."
    r_time = client.post(
        "/conversation",
        json={"text": "No, I meant 5 AM.", "conversation_id": cid, "current_date": ANCHOR_DATE, "timezone": USER_TZ},
    )
    assert r_time.json()["pending_plan"]["time"] == "05:00"

    # Correction B: Time -> "Change the time to 8 PM."
    r_time2 = client.post(
        "/conversation",
        json={"text": "Change the time to 8 PM.", "conversation_id": cid, "current_date": ANCHOR_DATE, "timezone": USER_TZ},
    )
    assert r_time2.json()["pending_plan"]["time"] == "20:00"

    # Correction C: Date -> "Not tomorrow, Friday."
    r_date = client.post(
        "/conversation",
        json={"text": "Not tomorrow, Friday.", "conversation_id": cid, "current_date": ANCHOR_DATE, "timezone": USER_TZ},
    )
    assert r_date.json()["pending_plan"]["date"] == "2026-10-30"

    # Correction D: Duration -> "Make it two hours."
    r_dur = client.post(
        "/conversation",
        json={"text": "Make it two hours.", "conversation_id": cid, "current_date": ANCHOR_DATE, "timezone": USER_TZ},
    )
    assert r_dur.json()["pending_plan"]["duration_minutes"] == 120


def test_7_accurate_confirmation_summaries(
    client: TestClient
) -> None:
    """7. Confirmation summaries accurately reflect task, date, start time, and duration in natural English."""
    r = client.post(
        "/conversation",
        json={"text": "I want to study tomorrow at 5 PM for two hours.", "current_date": ANCHOR_DATE, "timezone": USER_TZ},
    )
    assert r.status_code == 200
    summary = r.json()["reply_text"]
    # Required format: "Create a plan to study tomorrow, Thursday, October 29, at 5:00 PM for two hours?"
    assert "Create a plan to study" in summary
    assert "tomorrow, Thursday, October 29" in summary
    assert "at 5:00 PM" in summary
    assert "for two hours" in summary
    assert summary.endswith("?")


def test_8_no_database_write_before_explicit_confirmation(
    client: TestClient, store: InMemoryConversationStore
) -> None:
    """8. Never write to the database before explicit confirmation."""
    r1 = client.post(
        "/conversation",
        json={"text": "I want to study tomorrow evening.", "current_date": ANCHOR_DATE, "timezone": USER_TZ},
    )
    cid = r1.json()["conversation_id"]
    client.post("/conversation", json={"text": "At five.", "conversation_id": cid, "current_date": ANCHOR_DATE})
    client.post("/conversation", json={"text": "5 PM.", "conversation_id": cid, "current_date": ANCHOR_DATE})
    client.post("/conversation", json={"text": "Make it two hours.", "conversation_id": cid, "current_date": ANCHOR_DATE})

    # Zero plans written despite extensive discussion
    assert len(store.created_plans) == 0


def test_9_declining_confirmation_creates_no_plan(
    client: TestClient, store: InMemoryConversationStore
) -> None:
    """9. Declining confirmation cancels creation without writing to database."""
    r1 = client.post(
        "/conversation",
        json={"text": "I want to study tomorrow at 5 PM.", "current_date": ANCHOR_DATE, "timezone": USER_TZ},
    )
    cid = r1.json()["conversation_id"]

    # Decline
    r2 = client.post(
        "/conversation",
        json={"text": "No, cancel that.", "conversation_id": cid, "current_date": ANCHOR_DATE, "timezone": USER_TZ},
    )
    assert r2.status_code == 200
    assert r2.json()["state"] == "cancelled"
    assert "cancelled" in r2.json()["reply_text"].lower()
    assert len(store.created_plans) == 0


def test_10_confirming_creates_exactly_one_plan(
    client: TestClient, store: InMemoryConversationStore
) -> None:
    """10. Explicit confirmation creates exactly one plan in database."""
    r1 = client.post(
        "/conversation",
        json={"text": "I want to study tomorrow at 5 PM.", "current_date": ANCHOR_DATE, "timezone": USER_TZ},
    )
    cid = r1.json()["conversation_id"]

    r2 = client.post(
        "/conversation",
        json={"text": "Yes, please confirm.", "conversation_id": cid, "current_date": ANCHOR_DATE, "timezone": USER_TZ},
    )
    assert r2.status_code == 200
    data = r2.json()
    assert data["state"] == "completed"
    assert data["prompt_type"] == "success"
    assert len(store.created_plans) == 1
    created = store.created_plans[0]
    assert created["title"].lower() == "study"
    assert "2026-10-29T17:00:00" in created["planned_start"]


def test_11_repeated_confirmation_and_retries_do_not_create_duplicates(
    client: TestClient, store: InMemoryConversationStore
) -> None:
    """11. Repeated confirmations and retries do not create duplicate plans (idempotency)."""
    r1 = client.post(
        "/conversation",
        json={"text": "I want to study tomorrow at 5 PM.", "current_date": ANCHOR_DATE, "timezone": USER_TZ},
    )
    cid = r1.json()["conversation_id"]

    # First confirmation
    client.post("/conversation", json={"text": "Yes", "conversation_id": cid, "current_date": ANCHOR_DATE})
    assert len(store.created_plans) == 1

    # Repeated confirmation on same conversation
    r_repeat = client.post("/conversation", json={"text": "Yes", "conversation_id": cid, "current_date": ANCHOR_DATE})
    assert r_repeat.status_code == 200
    assert len(store.created_plans) == 1  # Exactly 1 plan, no duplicates


def test_12_cancellation_clears_pending_creation_safely(
    client: TestClient, store: InMemoryConversationStore, engine: ConversationEngine
) -> None:
    """12. Cancellation clears the pending creation safely."""
    r1 = client.post(
        "/conversation",
        json={"text": "I want to study tomorrow at 5 PM.", "current_date": ANCHOR_DATE, "timezone": USER_TZ},
    )
    cid = r1.json()["conversation_id"]

    r_cancel = client.post("/conversation/cancel")
    assert r_cancel.status_code == 200
    assert r_cancel.json()["state"] == "cancelled"

    # User active session is cleared
    assert engine.get_active_session_for_user(USER_ID) is None
    assert len(store.created_plans) == 0


def test_13_persistence_failures_do_not_produce_false_success(
    client: TestClient, store: InMemoryConversationStore
) -> None:
    """13. Persistence failures do not produce false success responses."""
    r1 = client.post(
        "/conversation",
        json={"text": "I want to study tomorrow at 5 PM.", "current_date": ANCHOR_DATE, "timezone": USER_TZ},
    )
    cid = r1.json()["conversation_id"]

    # Trigger failure on database write
    store.simulate_persistence_failure = True

    r2 = client.post(
        "/conversation",
        json={"text": "Yes", "conversation_id": cid, "current_date": ANCHOR_DATE},
    )
    assert r2.status_code >= 500
    # No false success
    assert len(store.created_plans) == 0


def test_14_web_and_esp32_use_same_orchestration_rules(
    client: TestClient, store: InMemoryConversationStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """14. Web and ESP32 voice interface use the same orchestration rules and business logic."""
    # Step A: User speaks incomplete request via ESP32 (/voice)
    client.app.dependency_overrides[get_stt_client] = lambda: FakeSTTClient(
        transcript="I want to study tomorrow evening."
    )
    v_headers = {"Authorization": f"Bearer {TOKEN}", "Accept": "audio/wav"}
    r_v1 = client.post(
        "/voice",
        files={"audio": ("voice.wav", _make_wav_bytes(), "audio/wav")},
        data={"current_date": ANCHOR_DATE, "timezone": USER_TZ},
        headers=v_headers,
    )
    assert r_v1.status_code == 200
    assert r_v1.headers["X-Intent"] == "clarify"
    cid = r_v1.headers.get("X-Conversation-Id")
    assert cid is not None

    # Step B: User provides ambiguous time via Web (/conversation) on SAME conversation
    r_web = client.post(
        "/conversation",
        json={"text": "At five.", "conversation_id": cid, "current_date": ANCHOR_DATE, "timezone": USER_TZ},
    )
    assert r_web.status_code == 200
    assert "5 AM or 5 PM" in r_web.json()["reply_text"]

    # Step C: User answers AM/PM via ESP32 (/voice)
    client.app.dependency_overrides[get_stt_client] = lambda: FakeSTTClient(transcript="5 PM.")
    r_v2 = client.post(
        "/voice",
        files={"audio": ("voice.wav", _make_wav_bytes(), "audio/wav")},
        data={"current_date": ANCHOR_DATE, "timezone": USER_TZ, "conversation_id": cid},
        headers=v_headers,
    )
    assert r_v2.status_code == 201
    assert r_v2.headers["X-Intent"] == "propose_plan"
    assert r_v2.headers["X-Needs-Button"] == "true"
    assert "Create a plan to study" in unquote(r_v2.headers["X-Reply-Text"])

    # Step D: User confirms via ESP32 speech
    client.app.dependency_overrides[get_stt_client] = lambda: FakeSTTClient(transcript="Yes, confirm.")
    r_v3 = client.post(
        "/voice",
        files={"audio": ("voice.wav", _make_wav_bytes(), "audio/wav")},
        data={"current_date": ANCHOR_DATE, "timezone": USER_TZ, "conversation_id": cid},
        headers=v_headers,
    )
    assert r_v3.status_code == 201
    # Exactly one plan created
    assert len(store.created_plans) == 1


def test_15_english_only_assistant_responses(
    client: TestClient
) -> None:
    """15. English-only assistant responses across clarification, confirmation, cancellation, and error flows."""
    turkish_chars = {"ç", "ğ", "ı", "ö", "ş", "ü", "Ç", "Ğ", "İ", "Ö", "Ş", "Ü"}

    # 1. Clarification response
    r1 = client.post(
        "/conversation",
        json={"text": "I want to study tomorrow.", "current_date": ANCHOR_DATE, "timezone": USER_TZ},
    )
    reply1 = r1.json()["reply_text"]
    assert not any(c in reply1 for c in turkish_chars)
    assert "what time" in reply1.lower()

    # 2. Confirmation summary response
    r2 = client.post(
        "/conversation",
        json={"text": "At 5 PM.", "conversation_id": r1.json()["conversation_id"], "current_date": ANCHOR_DATE},
    )
    reply2 = r2.json()["reply_text"]
    assert not any(c in reply2 for c in turkish_chars)
    assert "Create a plan to study" in reply2

    # 3. Cancellation response
    r3 = client.post(
        "/conversation",
        json={"text": "Cancel that.", "conversation_id": r1.json()["conversation_id"], "current_date": ANCHOR_DATE},
    )
    reply3 = r3.json()["reply_text"]
    assert not any(c in reply3 for c in turkish_chars)
    assert "cancelled" in reply3.lower()


def test_16_existing_plan_creation_and_status_update_compatibility(
    client: TestClient, store: InMemoryConversationStore
) -> None:
    """16. Existing plan creation (POST /plans) and update endpoints remain fully compatible."""
    # Test POST /plans direct creation
    plan_payload = {
        "parsed_plan": {
            "intent": "create_plan",
            "title": "Gym workout",
            "category": "sport",
            "date": "2026-10-29",
            "time": "08:00",
            "duration_minutes": 60,
            "recurrence": None,
            "language": "en",
            "needs_weather_check": False,
            "clarification_question": None,
            "confidence": 0.95,
        },
        "source": "text",
    }
    r = client.post("/plans", json=plan_payload)
    assert r.status_code == 201
    plan_id = r.json()["id"]
    assert len(store.created_plans) == 1

    # Verify active conversation is not affected
    conv = client.get("/conversation/active")
    assert conv.status_code == 200
    assert conv.json() is None


def test_unrelated_request_preserves_pending_plan(
    client: TestClient, store: InMemoryConversationStore
) -> None:
    """If user asks an unrelated question while a plan is pending, pending state is preserved."""
    r1 = client.post(
        "/conversation",
        json={"text": "I want to study tomorrow at 5 PM.", "current_date": ANCHOR_DATE, "timezone": USER_TZ},
    )
    cid = r1.json()["conversation_id"]
    assert r1.json()["state"] == "awaiting_confirmation"

    # User asks unrelated joke
    r_unrelated = client.post(
        "/conversation",
        json={"text": "Tell me a joke today.", "conversation_id": cid, "current_date": ANCHOR_DATE},
    )
    assert r_unrelated.status_code == 200
    # Pending plan is preserved!
    assert r_unrelated.json()["pending_plan"]["title"].lower() == "study"
    assert r_unrelated.json()["state"] == "awaiting_confirmation"
    assert len(store.created_plans) == 0
