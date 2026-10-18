from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.db.plans import AuthenticatedUser, get_plan_store
from app.main import app

PEPPER = "p" * 32
TOKEN_USER_ONE = "token-user-one"
TOKEN_USER_TWO = "token-user-two"
TOKEN_DEMO = "token-demo"


def _hash(token: str) -> str:
    return hashlib.sha256((token + PEPPER).encode("utf-8")).hexdigest()


class FakeOutcomeStore:
    """In-memory store with the methods POST /plans/{id}/outcome relies on."""

    def __init__(self) -> None:
        self.tokens: dict[str, tuple[AuthenticatedUser, str | None]] = {}
        self.plans: dict[str, dict[str, object]] = {}
        self.outcomes: list[dict[str, object]] = []
        self.get_plan_calls: list[tuple[str, str]] = []

    def get_user_for_token_hash(self, token_hash: str):
        return self.tokens.get(token_hash)

    def add_plan(self, user_id: str) -> str:
        plan_id = str(uuid4())
        self.plans[plan_id] = {"id": plan_id, "user_id": user_id}
        return plan_id

    def get_plan(self, *, user_id: str, plan_id: str) -> dict[str, object] | None:
        self.get_plan_calls.append((user_id, plan_id))
        plan = self.plans.get(plan_id)
        if plan is None or plan["user_id"] != user_id:
            return None
        return plan

    def create_outcome(
        self, *, user_id: str, plan_id: str, outcome: dict[str, object]
    ) -> dict[str, object]:
        row = {
            "id": str(uuid4()),
            "plan_id": plan_id,
            "user_id": user_id,
            **outcome,
            "reported_at": datetime.now(timezone.utc).isoformat(),
        }
        self.outcomes.append(row)
        return row


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "app.api.plans.get_settings",
        lambda: SimpleNamespace(token_hash_pepper=SecretStr(PEPPER)),
    )
    fake = FakeOutcomeStore()
    demo_expiry = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    fake.tokens[_hash(TOKEN_USER_ONE)] = (
        AuthenticatedUser("user-one", "Europe/Istanbul", False, None),
        None,
    )
    fake.tokens[_hash(TOKEN_USER_TWO)] = (
        AuthenticatedUser("user-two", "Europe/Istanbul", False, None),
        None,
    )
    fake.tokens[_hash(TOKEN_DEMO)] = (
        AuthenticatedUser("demo-user", "Europe/Istanbul", True, demo_expiry),
        demo_expiry,
    )
    app.dependency_overrides[get_plan_store] = lambda: fake
    yield fake
    app.dependency_overrides.clear()


@pytest.fixture
def client(store) -> TestClient:
    return TestClient(app)


def _auth(token: str = TOKEN_USER_ONE) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _post(client: TestClient, plan_id: str, body: dict[str, object], token: str | None = TOKEN_USER_ONE):
    headers = _auth(token) if token else {}
    return client.post(f"/plans/{plan_id}/outcome", json=body, headers=headers)


DONE = {
    "status": "done",
    "actual_start": "2026-10-06T18:17:00+03:00",
    "postponed_to": None,
    "note": None,
    "reported_via": "web",
}


def test_done_outcome_returns_201_with_contract_body(client, store) -> None:
    plan_id = store.add_plan("user-one")

    response = _post(client, plan_id, DONE)

    assert response.status_code == 201
    body = response.json()
    assert set(body) == {
        "id",
        "plan_id",
        "status",
        "actual_start",
        "postponed_to",
        "note",
        "reported_via",
        "reported_at",
    }
    assert body["plan_id"] == plan_id
    assert body["status"] == "done"
    assert datetime.fromisoformat(body["actual_start"]) == datetime.fromisoformat(
        "2026-10-06T18:17:00+03:00"
    )
    assert body["reported_via"] == "web"
    assert store.outcomes[0]["user_id"] == "user-one"
    assert store.get_plan_calls == [("user-one", plan_id)]


def test_device_can_postpone_without_target_time(client, store) -> None:
    plan_id = store.add_plan("user-one")

    response = _post(client, plan_id, {"status": "postponed", "reported_via": "device"})

    assert response.status_code == 201
    assert response.json()["postponed_to"] is None
    assert response.json()["reported_via"] == "device"


def test_postponed_outcome_keeps_target_time_with_offset(client, store) -> None:
    plan_id = store.add_plan("user-one")

    response = _post(
        client,
        plan_id,
        {
            "status": "postponed",
            "postponed_to": "2026-10-08T19:00:00+03:00",
            "reported_via": "web",
        },
    )

    assert response.status_code == 201
    stored = store.outcomes[0]["postponed_to"]
    assert datetime.fromisoformat(stored) == datetime.fromisoformat("2026-10-08T19:00:00+03:00")
    assert datetime.fromisoformat(stored).utcoffset() is not None


def test_every_report_is_a_new_event(client, store) -> None:
    plan_id = store.add_plan("user-one")

    first = _post(client, plan_id, {"status": "postponed", "reported_via": "device"})
    second = _post(client, plan_id, DONE)

    assert first.status_code == second.status_code == 201
    assert first.json()["id"] != second.json()["id"]
    assert [o["status"] for o in store.outcomes] == ["postponed", "done"]


def test_demo_user_can_report_outcomes(client, store) -> None:
    plan_id = store.add_plan("demo-user")

    response = _post(client, plan_id, DONE, token=TOKEN_DEMO)

    assert response.status_code == 201


def test_other_users_plan_returns_404(client, store) -> None:
    plan_id = store.add_plan("user-two")

    response = _post(client, plan_id, DONE)

    assert response.status_code == 404
    assert response.json() == {"error": "not_found", "message": "Plan not found."}
    assert store.outcomes == []


def test_unknown_plan_returns_404(client, store) -> None:
    response = _post(client, str(uuid4()), DONE)

    assert response.status_code == 404
    assert response.json()["error"] == "not_found"


def test_non_uuid_plan_id_returns_404_without_store_lookup(client, store) -> None:
    response = _post(client, "not-a-uuid", DONE)

    assert response.status_code == 404
    assert response.json()["error"] == "not_found"
    assert store.get_plan_calls == []


@pytest.mark.parametrize("token", [None, "unknown-token"])
def test_missing_or_invalid_token_returns_401(client, store, token) -> None:
    plan_id = store.add_plan("user-one")

    response = _post(client, plan_id, DONE, token=token)

    assert response.status_code == 401
    assert response.json()["error"] == "unauthorized"
    assert store.outcomes == []


def test_auth_is_checked_before_body_validation(client, store) -> None:
    response = _post(client, str(uuid4()), {"status": "bogus"}, token=None)

    assert response.status_code == 401


@pytest.mark.parametrize(
    "body",
    [
        {**DONE, "status": "finished"},
        {**DONE, "reported_via": "email"},
        {key: value for key, value in DONE.items() if key != "reported_via"},
        {key: value for key, value in DONE.items() if key != "status"},
        {**DONE, "extra": True},
        {**DONE, "actual_start": "2026-10-06T18:17:00"},
        {**DONE, "postponed_to": "2026-10-08T19:00:00+03:00"},
        {"status": "skipped", "postponed_to": "2026-10-08T19:00:00+03:00", "reported_via": "web"},
    ],
    ids=[
        "unknown-status",
        "unknown-reported-via",
        "missing-reported-via",
        "missing-status",
        "extra-field",
        "timestamp-without-offset",
        "postponed-to-on-done",
        "postponed-to-on-skipped",
    ],
)
def test_invalid_body_returns_contract_422(client, store, body) -> None:
    plan_id = store.add_plan("user-one")

    response = _post(client, plan_id, body)

    assert response.status_code == 422
    assert response.json()["error"] == "validation_error"
    assert store.outcomes == []
