from __future__ import annotations

from datetime import date
import hashlib
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.ai.llm import (
    LLMConfigurationError,
    LLMParseError,
    LLMResponseError,
    LLMUnavailableError,
    get_llm_client,
)
from app.api.errors import APIError
from app.api.parse import ParseRequest, parse_text
import app.api.plans as plans_api
from app.db.plans import AuthenticatedUser, get_plan_store
from app.main import app
from app.schemas.parsed_plan import ParsedPlan

PEPPER = "p" * 32
TOKEN = "valid-test-token"
TOKEN_HASH = hashlib.sha256((TOKEN + PEPPER).encode("utf-8")).hexdigest()
USER_TZ = "Europe/Istanbul"


def _user(**changes: Any) -> AuthenticatedUser:
    data: dict[str, Any] = {
        "id": "user-test-123",
        "timezone": USER_TZ,
        "is_demo": False,
        "demo_expires_at": None,
    }
    data.update(changes)
    return AuthenticatedUser(**data)  # type: ignore[arg-type]


class FakeTokenStore:
    def __init__(self, tokens: dict[str, tuple[AuthenticatedUser, str | None]] | None = None) -> None:
        self.tokens = tokens if tokens is not None else {TOKEN_HASH: (_user(), None)}
        self.created_plans: list[dict[str, Any]] = []

    def get_user_for_token_hash(self, token_hash: str) -> tuple[AuthenticatedUser, str | None] | None:
        return self.tokens.get(token_hash)

    def create_plan(self, plan: dict[str, Any]) -> dict[str, Any]:
        self.created_plans.append(plan)
        return plan


class FakeLLMClient:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = list(responses)
        self.calls: list[list[dict[str, str]]] = []

    def complete_json(self, messages: list[dict[str, str]], **kwargs: Any) -> Any:
        self.calls.append(messages)
        if not self.responses:
            raise RuntimeError("No responses left in FakeLLMClient")
        next_resp = self.responses.pop(0)
        if isinstance(next_resp, Exception):
            raise next_resp
        return next_resp


def _valid_create_plan(**changes: Any) -> dict[str, Any]:
    plan: dict[str, Any] = {
        "intent": "create_plan",
        "title": "Koşu",
        "category": "sport",
        "date": "2026-10-06",
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
        "date": "2026-10-06",
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


@pytest.fixture(autouse=True)
def _patch_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = SimpleNamespace(
        token_hash_pepper=SecretStr(PEPPER),
        environment="development",
        allowed_origins=[],
    )
    monkeypatch.setattr(plans_api, "get_settings", lambda: settings)


@pytest.fixture
def fake_store() -> FakeTokenStore:
    store = FakeTokenStore()
    app.dependency_overrides[get_plan_store] = lambda: store
    yield store
    app.dependency_overrides.pop(get_plan_store, None)


@pytest.fixture
def client(fake_store: FakeTokenStore) -> TestClient:
    return TestClient(app)


def _auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


# -----------------------------------------------------------------------------
# 1. Successful Parse Scenarios (create_plan, clarify, unsupported)
# -----------------------------------------------------------------------------


def test_parse_create_plan_success(client: TestClient, fake_store: FakeTokenStore) -> None:
    llm_resp = _valid_create_plan()
    fake_llm = FakeLLMClient([llm_resp])
    app.dependency_overrides[get_llm_client] = lambda: fake_llm

    try:
        response = client.post(
            "/parse",
            json={
                "text": "Yarın 18'de koşuya çıkacağım.",
                "language": "tr",
                "current_date": "2026-10-05",
                "timezone": "Europe/Istanbul",
            },
            headers=_auth_headers(),
        )
    finally:
        app.dependency_overrides.pop(get_llm_client, None)

    assert response.status_code == 200
    data = response.json()

    # Response is directly the ParsedPlan object (no wrapper)
    assert "parsed_plan" not in data
    assert "data" not in data
    assert data["intent"] == "create_plan"
    assert data["title"] == "Koşu"
    assert data["category"] == "sport"
    assert data["date"] == "2026-10-06"
    assert data["time"] == "18:00"
    assert data["needs_weather_check"] is True
    assert data["clarification_question"] is None

    # Validate against schema
    ParsedPlan.model_validate(data)

    # Ensure no plan was persisted
    assert len(fake_store.created_plans) == 0
    assert len(fake_llm.calls) == 1


def test_parse_clarify_success(client: TestClient, fake_store: FakeTokenStore) -> None:
    llm_resp = _valid_clarify()
    fake_llm = FakeLLMClient([llm_resp])
    app.dependency_overrides[get_llm_client] = lambda: fake_llm

    try:
        response = client.post(
            "/parse",
            json={
                "text": "Yarın koşuya çıkacağım.",
                "language": "tr",
                "current_date": "2026-10-05",
            },
            headers=_auth_headers(),
        )
    finally:
        app.dependency_overrides.pop(get_llm_client, None)

    assert response.status_code == 200
    data = response.json()
    assert data["intent"] == "clarify"
    assert data["clarification_question"] == "Koşuya saat kaçta çıkmak istersiniz?"
    ParsedPlan.model_validate(data)
    assert len(fake_store.created_plans) == 0


def test_parse_unsupported_success(client: TestClient, fake_store: FakeTokenStore) -> None:
    llm_resp = _valid_unsupported()
    fake_llm = FakeLLMClient([llm_resp])
    app.dependency_overrides[get_llm_client] = lambda: fake_llm

    try:
        response = client.post(
            "/parse",
            json={
                "text": "Bugün hava nasıl?",
                "current_date": "2026-10-05",
            },
            headers=_auth_headers(),
        )
    finally:
        app.dependency_overrides.pop(get_llm_client, None)

    assert response.status_code == 200
    data = response.json()
    assert data["intent"] == "unsupported"
    assert data["title"] is None
    assert data["date"] is None
    assert data["needs_weather_check"] is False
    assert data["clarification_question"] is None
    ParsedPlan.model_validate(data)
    assert len(fake_store.created_plans) == 0


# -----------------------------------------------------------------------------
# 2. Authentication Tests (401 Unauthorized)
# -----------------------------------------------------------------------------


def test_parse_missing_token_returns_401(client: TestClient) -> None:
    response = client.post(
        "/parse",
        json={"text": "Yarın 18'de koşu", "current_date": "2026-10-05"},
    )
    assert response.status_code == 401
    assert response.json()["error"] == "unauthorized"


def test_parse_invalid_token_returns_401(client: TestClient) -> None:
    response = client.post(
        "/parse",
        json={"text": "Yarın 18'de koşu", "current_date": "2026-10-05"},
        headers={"Authorization": "Bearer invalid-token-string"},
    )
    assert response.status_code == 401
    assert response.json()["error"] == "unauthorized"


# -----------------------------------------------------------------------------
# 3. Validation Tests (422 Validation Error)
# -----------------------------------------------------------------------------


def test_parse_missing_required_fields_returns_422(client: TestClient) -> None:
    # Missing text
    resp1 = client.post(
        "/parse",
        json={"current_date": "2026-10-05"},
        headers=_auth_headers(),
    )
    assert resp1.status_code == 422
    assert resp1.json()["error"] == "validation_error"

    # Missing current_date
    resp2 = client.post(
        "/parse",
        json={"text": "Yarın 18'de koşu"},
        headers=_auth_headers(),
    )
    assert resp2.status_code == 422
    assert resp2.json()["error"] == "validation_error"


def test_parse_invalid_calendar_date_returns_422(client: TestClient) -> None:
    resp = client.post(
        "/parse",
        json={"text": "Yarın 18'de koşu", "current_date": "2026-02-31"},
        headers=_auth_headers(),
    )
    assert resp.status_code == 422
    assert resp.json()["error"] == "validation_error"


def test_parse_invalid_language_returns_422(client: TestClient) -> None:
    resp = client.post(
        "/parse",
        json={"text": "Yarın 18'de koşu", "current_date": "2026-10-05", "language": "de"},
        headers=_auth_headers(),
    )
    assert resp.status_code == 422
    assert resp.json()["error"] == "validation_error"


def test_parse_extra_forbidden_field_returns_422(client: TestClient) -> None:
    resp = client.post(
        "/parse",
        json={
            "text": "Yarın 18'de koşu",
            "current_date": "2026-10-05",
            "unsupported_extra": "forbidden",
        },
        headers=_auth_headers(),
    )
    assert resp.status_code == 422
    assert resp.json()["error"] == "validation_error"


def test_parse_mismatched_timezone_returns_422(client: TestClient) -> None:
    # User's registered timezone is Europe/Istanbul
    resp = client.post(
        "/parse",
        json={
            "text": "Yarın 18'de koşu",
            "current_date": "2026-10-05",
            "timezone": "America/New_York",
        },
        headers=_auth_headers(),
    )
    assert resp.status_code == 422
    assert resp.json()["error"] == "validation_error"
    assert "does not match registered" in resp.json()["message"]


def test_parse_matching_timezone_succeeds(client: TestClient) -> None:
    fake_llm = FakeLLMClient([_valid_create_plan()])
    app.dependency_overrides[get_llm_client] = lambda: fake_llm

    try:
        resp = client.post(
            "/parse",
            json={
                "text": "Yarın 18'de koşu",
                "current_date": "2026-10-05",
                "timezone": "Europe/Istanbul",
            },
            headers=_auth_headers(),
        )
    finally:
        app.dependency_overrides.pop(get_llm_client, None)

    assert resp.status_code == 200
    assert resp.json()["intent"] == "create_plan"


def test_parse_omitted_timezone_uses_user_timezone(client: TestClient) -> None:
    fake_llm = FakeLLMClient([_valid_create_plan()])
    app.dependency_overrides[get_llm_client] = lambda: fake_llm

    try:
        resp = client.post(
            "/parse",
            json={
                "text": "Yarın 18'de koşu",
                "current_date": "2026-10-05",
            },
            headers=_auth_headers(),
        )
    finally:
        app.dependency_overrides.pop(get_llm_client, None)

    assert resp.status_code == 200
    assert resp.json()["intent"] == "create_plan"
    assert "Europe/Istanbul" in fake_llm.calls[0][1]["content"]


# -----------------------------------------------------------------------------
# 4. Retry and Failure Handling (502 parse_failed)
# -----------------------------------------------------------------------------


def test_parse_retry_succeeds_after_initial_invalid_output(
    client: TestClient, fake_store: FakeTokenStore
) -> None:
    invalid_output = {"intent": "invalid_intent_value", "extra": "garbage"}
    valid_output = _valid_create_plan()

    fake_llm = FakeLLMClient([invalid_output, valid_output])
    app.dependency_overrides[get_llm_client] = lambda: fake_llm

    try:
        response = client.post(
            "/parse",
            json={"text": "Yarın 18'de koşu", "current_date": "2026-10-05"},
            headers=_auth_headers(),
        )
    finally:
        app.dependency_overrides.pop(get_llm_client, None)

    assert response.status_code == 200
    data = response.json()
    assert data["intent"] == "create_plan"
    assert len(fake_llm.calls) == 2
    assert "IMPORTANT: The previous output failed schema validation" in fake_llm.calls[1][1]["content"]
    assert len(fake_store.created_plans) == 0


def test_parse_retry_succeeds_after_initial_llm_parse_error(
    client: TestClient, fake_store: FakeTokenStore
) -> None:
    parse_error = LLMParseError("Upstream returned invalid JSON syntax")
    valid_output = _valid_create_plan()

    fake_llm = FakeLLMClient([parse_error, valid_output])
    app.dependency_overrides[get_llm_client] = lambda: fake_llm

    try:
        response = client.post(
            "/parse",
            json={"text": "Yarın 18'de koşu", "current_date": "2026-10-05"},
            headers=_auth_headers(),
        )
    finally:
        app.dependency_overrides.pop(get_llm_client, None)

    assert response.status_code == 200
    assert response.json()["intent"] == "create_plan"
    assert len(fake_llm.calls) == 2
    assert len(fake_store.created_plans) == 0


def test_parse_fails_with_502_after_two_invalid_attempts(
    client: TestClient, fake_store: FakeTokenStore
) -> None:
    invalid_1 = {"missing_fields": True}
    invalid_2 = LLMParseError("Still invalid JSON")

    fake_llm = FakeLLMClient([invalid_1, invalid_2])
    app.dependency_overrides[get_llm_client] = lambda: fake_llm

    try:
        response = client.post(
            "/parse",
            json={"text": "Yarın 18'de koşu", "current_date": "2026-10-05"},
            headers=_auth_headers(),
        )
    finally:
        app.dependency_overrides.pop(get_llm_client, None)

    assert response.status_code == 502
    assert response.json()["error"] == "parse_failed"
    assert len(fake_llm.calls) == 2
    assert len(fake_store.created_plans) == 0


# -----------------------------------------------------------------------------
# 5. LLM Provider Errors (503 llm_unavailable)
# -----------------------------------------------------------------------------


def test_parse_llm_unavailable_returns_503(client: TestClient) -> None:
    timeout_err = LLMUnavailableError("Connection timed out after 30s")
    fake_llm = FakeLLMClient([timeout_err])
    app.dependency_overrides[get_llm_client] = lambda: fake_llm

    try:
        response = client.post(
            "/parse",
            json={"text": "Yarın 18'de koşu", "current_date": "2026-10-05"},
            headers=_auth_headers(),
        )
    finally:
        app.dependency_overrides.pop(get_llm_client, None)

    assert response.status_code == 503
    assert response.json()["error"] == "llm_unavailable"
    assert len(fake_llm.calls) == 1


def test_parse_llm_response_error_returns_503(client: TestClient) -> None:
    provider_err = LLMResponseError(429, "Rate limit reached upstream")
    fake_llm = FakeLLMClient([provider_err])
    app.dependency_overrides[get_llm_client] = lambda: fake_llm

    try:
        response = client.post(
            "/parse",
            json={"text": "Yarın 18'de koşu", "current_date": "2026-10-05"},
            headers=_auth_headers(),
        )
    finally:
        app.dependency_overrides.pop(get_llm_client, None)

    assert response.status_code == 503
    assert response.json()["error"] == "llm_unavailable"
    assert "Rate limit" not in response.json()["message"]


def test_parse_llm_configuration_error_returns_503(client: TestClient) -> None:
    cfg_err = LLMConfigurationError("API key missing")
    fake_llm = FakeLLMClient([cfg_err])
    app.dependency_overrides[get_llm_client] = lambda: fake_llm

    try:
        response = client.post(
            "/parse",
            json={"text": "Yarın 18'de koşu", "current_date": "2026-10-05"},
            headers=_auth_headers(),
        )
    finally:
        app.dependency_overrides.pop(get_llm_client, None)

    assert response.status_code == 503
    assert response.json()["error"] == "llm_unavailable"


# -----------------------------------------------------------------------------
# 6. Reusable parse_text Function Tests (B5 Voice Pipeline Integration)
# -----------------------------------------------------------------------------


def test_parse_text_direct_call_success() -> None:
    fake_llm = FakeLLMClient([_valid_create_plan()])
    parsed = parse_text(
        text="Yarın 18'de koşuya çıkacağım.",
        current_date=date(2026, 10, 5),
        timezone="Europe/Istanbul",
        language="tr",
        llm_client=fake_llm,  # type: ignore[arg-type]
    )
    assert isinstance(parsed, ParsedPlan)
    assert parsed.root["intent"] == "create_plan"
    assert parsed.root["title"] == "Koşu"
    assert len(fake_llm.calls) == 1


def test_parse_text_empty_input_raises_validation_error() -> None:
    with pytest.raises(APIError) as exc_info:
        parse_text(
            text="   ",
            current_date="2026-10-05",
            timezone="Europe/Istanbul",
        )
    assert exc_info.value.status_code == 422
    assert exc_info.value.error == "validation_error"


def test_parse_text_invalid_date_raises_validation_error() -> None:
    with pytest.raises(APIError) as exc_info:
        parse_text(
            text="Koşu",
            current_date="invalid-date-format",
            timezone="Europe/Istanbul",
        )
    assert exc_info.value.status_code == 422
    assert exc_info.value.error == "validation_error"


def test_parse_text_invalid_timezone_raises_validation_error() -> None:
    with pytest.raises(APIError) as exc_info:
        parse_text(
            text="Koşu",
            current_date="2026-10-05",
            timezone="Invalid/Timezone_Name",
        )
    assert exc_info.value.status_code == 422
    assert exc_info.value.error == "validation_error"
