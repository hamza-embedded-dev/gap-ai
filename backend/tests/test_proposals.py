from __future__ import annotations

import datetime
from typing import Any
import uuid

import pytest
from starlette.testclient import TestClient

from app.ai.tts import GroqTTSClient, get_tts_client
from app.api.plans import current_user
from app.db.plans import AuthenticatedUser, PlanStore, get_plan_store
from app.main import app


class InMemoryProposalPlanStore:
    def __init__(self) -> None:
        self.proposals: dict[str, list[dict[str, Any]]] = {}
        self.created_plans: list[dict[str, Any]] = []

    def get_user_for_token_hash(self, token_hash: str) -> None:
        return None

    def get_user_for_supabase_jwt(self, jwt_token: str) -> None:
        return None

    def create_plan(self, plan: dict[str, Any]) -> dict[str, Any]:
        p = {
            "id": str(uuid.uuid4()),
            "title": plan["title"],
            "category": plan.get("category", "fitness"),
            "planned_start": plan["planned_start"],
            "planned_end": plan["planned_end"],
            "recurrence_rule": plan.get("recurrence_rule"),
            "source": plan.get("source", "voice"),
            "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "latest_outcome": None,
        }
        self.created_plans.append(p)
        return p

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
            "title": proposal["title"],
            "category": proposal.get("category", "fitness"),
            "planned_start": proposal["planned_start"],
            "planned_end": proposal["planned_end"],
            "duration_minutes": proposal.get("duration_minutes", 60),
            "recurrence_rule": proposal.get("recurrence_rule"),
            "status": "pending",
            "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
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


class DummyTTSClient:
    def synthesize(self, text: str) -> bytes:
        # 44-byte dummy WAV
        return b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x80>\x00\x00\x00}\x00\x00\x02\x00\x10\x00data\x00\x00\x00\x00"


@pytest.fixture
def auth_user() -> AuthenticatedUser:
    return AuthenticatedUser(
        id="user-hamza-123",
        timezone="Europe/Istanbul",
        is_demo=False,
        demo_expires_at=None,
        display_name="Hamza Emin",
    )


@pytest.fixture
def store() -> InMemoryProposalPlanStore:
    return InMemoryProposalPlanStore()


@pytest.fixture
def client(auth_user: AuthenticatedUser, store: InMemoryProposalPlanStore) -> TestClient:
    app.dependency_overrides[current_user] = lambda: auth_user
    app.dependency_overrides[get_plan_store] = lambda: store
    app.dependency_overrides[get_tts_client] = lambda: DummyTTSClient()
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_get_pending_proposal_none(client: TestClient) -> None:
    resp = client.get("/plans/proposals/pending")
    assert resp.status_code == 200
    assert resp.json() is None


def test_accept_proposal_404_when_none(client: TestClient) -> None:
    resp = client.post("/plans/proposals/accept")
    assert resp.status_code == 404
    data = resp.json()
    assert data["error"] == "not_found"


def test_reject_proposal_404_when_none(client: TestClient) -> None:
    resp = client.post("/plans/proposals/reject")
    assert resp.status_code == 404
    data = resp.json()
    assert data["error"] == "not_found"


def test_accept_proposal_json(client: TestClient, store: InMemoryProposalPlanStore) -> None:
    store.create_plan_proposal(
        user_id="user-hamza-123",
        proposal={
            "title": "Evening Run",
            "category": "fitness",
            "planned_start": "2026-10-28T18:00:00+03:00",
            "planned_end": "2026-10-28T19:00:00+03:00",
            "duration_minutes": 60,
        },
    )

    resp = client.post("/plans/proposals/accept", headers={"Accept": "application/json"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "accepted"
    assert data["plan"]["title"] == "Evening Run"
    assert len(store.created_plans) == 1
    assert store.created_plans[0]["title"] == "Evening Run"


def test_accept_proposal_wav(client: TestClient, store: InMemoryProposalPlanStore) -> None:
    store.create_plan_proposal(
        user_id="user-hamza-123",
        proposal={
            "title": "Swimming",
            "category": "fitness",
            "planned_start": "2026-10-28T10:00:00+03:00",
            "planned_end": "2026-10-28T11:00:00+03:00",
            "duration_minutes": 60,
        },
    )

    resp = client.post("/plans/proposals/accept", headers={"Accept": "audio/wav, application/json"})
    assert resp.status_code == 200
    assert resp.headers["Content-Type"] == "audio/wav"
    assert resp.headers["X-Status"] == "accepted"
    assert resp.content.startswith(b"RIFF")


def test_reject_proposal_json(client: TestClient, store: InMemoryProposalPlanStore) -> None:
    prop = store.create_plan_proposal(
        user_id="user-hamza-123",
        proposal={
            "title": "Cycling",
            "category": "fitness",
            "planned_start": "2026-10-28T14:00:00+03:00",
            "planned_end": "2026-10-28T15:00:00+03:00",
            "duration_minutes": 60,
        },
    )

    resp = client.post("/plans/proposals/reject", headers={"Accept": "application/json"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "rejected"
    assert data["proposal_id"] == prop["id"]
    assert len(store.created_plans) == 0


def test_reject_proposal_wav(client: TestClient, store: InMemoryProposalPlanStore) -> None:
    prop = store.create_plan_proposal(
        user_id="user-hamza-123",
        proposal={
            "title": "Pilates",
            "category": "fitness",
            "planned_start": "2026-10-28T09:00:00+03:00",
            "planned_end": "2026-10-28T10:00:00+03:00",
            "duration_minutes": 60,
        },
    )

    resp = client.post("/plans/proposals/reject", headers={"Accept": "audio/wav, application/json"})
    assert resp.status_code == 200
    assert resp.headers["Content-Type"] == "audio/wav"
    assert resp.headers["X-Status"] == "rejected"
    assert resp.headers["X-Proposal-Id"] == prop["id"]
    assert resp.content.startswith(b"RIFF")
