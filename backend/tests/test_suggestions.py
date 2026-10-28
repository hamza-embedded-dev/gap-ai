from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.ai.llm import get_llm_client
from app.api.suggestions import get_suggestion_for_plan
from app.db.plans import AuthenticatedUser, get_plan_store
from app.main import app

PEPPER = "p" * 32
TOKEN_USER_ONE = "token-user-one"
TOKEN_USER_TWO = "token-user-two"


def _hash(token: str) -> str:
    return hashlib.sha256((token + PEPPER).encode("utf-8")).hexdigest()


class FakeSuggestionStore:
    def __init__(self) -> None:
        self.tokens: dict[str, tuple[AuthenticatedUser, str | None]] = {}
        self.plans: dict[str, dict[str, Any]] = {}
        self.suggestions: dict[str, dict[str, Any]] = {}
        self.personalization: dict[str, dict[str, Any]] = {}

    def get_user_for_token_hash(self, token_hash: str):
        return self.tokens.get(token_hash)

    def get_personalization(self, *, user_id: str):
        return self.personalization.get(user_id, {})

    def reset_personalization(self, *, user_id: str):
        self.personalization.pop(user_id, None)

    def add_plan(
        self,
        user_id: str,
        *,
        title: str = "Koşu",
        planned_start: str | None = None,
        planned_end: str | None = None,
        latest_outcome: dict[str, Any] | None = None,
    ) -> str:
        plan_id = str(uuid4())
        now = datetime.now(timezone.utc)
        start = planned_start or (now + timedelta(hours=1)).isoformat()
        end = planned_end or (now + timedelta(hours=2)).isoformat()
        self.plans[plan_id] = {
            "id": plan_id,
            "user_id": user_id,
            "title": title,
            "category": "sport",
            "planned_start": start,
            "planned_end": end,
            "latest_outcome": latest_outcome,
        }
        return plan_id

    def get_plan(self, *, user_id: str, plan_id: str) -> dict[str, Any] | None:
        plan = self.plans.get(plan_id)
        if plan is None or plan["user_id"] != user_id:
            return None
        return plan

    def list_plans(self, *, user_id: str) -> list[dict[str, Any]]:
        return [p for p in self.plans.values() if p["user_id"] == user_id]

    def get_suggestion(self, user_id: str, plan_id: str) -> dict[str, Any] | None:
        return self.suggestions.get(f"{user_id}:{plan_id}")

    def save_suggestion(
        self, user_id: str, plan_id: str, suggestion_data: dict[str, Any]
    ) -> dict[str, Any]:
        key = f"{user_id}:{plan_id}"
        stored = {**suggestion_data, "created_at": datetime.now(timezone.utc).isoformat()}
        self.suggestions[key] = stored
        return stored

    def refresh_suggestion(self, user_id: str, plan_id: str, suggestion_data: dict[str, Any]):
        return self.save_suggestion(user_id, plan_id, suggestion_data)


@pytest.fixture
def test_setup(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "app.api.plans.get_settings",
        lambda: SimpleNamespace(token_hash_pepper=SecretStr(PEPPER)),
    )
    fake_store = FakeSuggestionStore()
    fake_store.tokens[_hash(TOKEN_USER_ONE)] = (
        AuthenticatedUser("user-one", "Europe/Istanbul", False, None),
        None,
    )
    fake_store.tokens[_hash(TOKEN_USER_TWO)] = (
        AuthenticatedUser("user-two", "Europe/Istanbul", False, None),
        None,
    )

    mock_llm = MagicMock()
    mock_llm.complete.return_value = "Hava durumu veya geçmiş alışkanlık nedeniyle erteleme önerisi."

    app.dependency_overrides[get_plan_store] = lambda: fake_store
    app.dependency_overrides[get_llm_client] = lambda: mock_llm

    client = TestClient(app)
    try:
        yield client, fake_store, mock_llm
    finally:
        app.dependency_overrides.clear()


def test_suggestion_requires_authentication(test_setup):
    client, fake_store, _ = test_setup
    plan_id = fake_store.add_plan("user-one")

    # 1. No auth header -> 401
    resp = client.get(f"/plans/{plan_id}/suggestion")
    assert resp.status_code == 401
    assert resp.json()["error"] == "unauthorized"

    # 2. Invalid token -> 401
    resp = client.get(
        f"/plans/{plan_id}/suggestion",
        headers={"Authorization": "Bearer invalid-token"},
    )
    assert resp.status_code == 401
    assert resp.json()["error"] == "unauthorized"


def test_suggestion_not_found_or_forbidden_returns_404(test_setup):
    client, fake_store, _ = test_setup
    plan_id_user_two = fake_store.add_plan("user-two")
    random_id = str(uuid4())
    headers = {"Authorization": f"Bearer {TOKEN_USER_ONE}"}

    # 1. Non-existent plan -> 404
    resp = client.get(f"/plans/{random_id}/suggestion", headers=headers)
    assert resp.status_code == 404
    assert resp.json()["error"] == "not_found"

    # 2. Plan belongs to user-two -> 404 (contract K-1: not 403)
    resp = client.get(f"/plans/{plan_id_user_two}/suggestion", headers=headers)
    assert resp.status_code == 404
    assert resp.json()["error"] == "not_found"

    # 3. Invalid UUID format -> 404
    resp = client.get("/plans/not-a-valid-uuid/suggestion", headers=headers)
    assert resp.status_code == 404
    assert resp.json()["error"] == "not_found"


def test_existing_suggestion_returned_unmodified(test_setup):
    client, fake_store, mock_llm = test_setup
    plan_id = fake_store.add_plan("user-one")
    headers = {"Authorization": f"Bearer {TOKEN_USER_ONE}"}

    saved_suggestion = {
        "plan_id": plan_id,
        "reason": "weather",
        "message": "Önceden kaydedilmiş öneri mesajı.",
        "proposed_start": "2026-10-08T19:00:00+03:00",
        "proposed_end": "2026-10-08T20:00:00+03:00",
        "evidence": {"forecast": "rain", "adherence_pct": 50.0},
    }
    fake_store.suggestions[f"user-one:{plan_id}"] = saved_suggestion

    resp = client.get(f"/plans/{plan_id}/suggestion", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["suggestion"] == saved_suggestion
    # Should not call LLM if suggestion already existed
    mock_llm.complete.assert_not_called()


def test_insufficient_outcome_history_returns_null_without_model_call(test_setup):
    client, fake_store, mock_llm = test_setup
    headers = {"Authorization": f"Bearer {TOKEN_USER_ONE}"}
    plan_id = fake_store.add_plan("user-one")
    response = client.get(f"/plans/{plan_id}/suggestion", headers=headers)
    assert response.status_code == 200
    assert response.json() == {"suggestion": None}
    mock_llm.complete.assert_not_called()


def test_suggestion_refreshes_after_a_newer_outcome(test_setup, monkeypatch: pytest.MonkeyPatch):
    client, fake_store, mock_llm = test_setup
    headers = {"Authorization": f"Bearer {TOKEN_USER_ONE}"}
    now = datetime.now(timezone.utc)
    for days in (3, 4, 5):
        fake_store.add_plan(
            "user-one",
            planned_start=(now - timedelta(days=days, hours=2)).isoformat(),
            planned_end=(now - timedelta(days=days, hours=1)).isoformat(),
            latest_outcome={"status": "skipped", "reported_at": "2026-01-01T00:00:00+00:00"},
        )
    target_id = fake_store.add_plan("user-one")
    monkeypatch.setattr(
        "app.services.weather.WeatherService.get_forecast",
        lambda *args, **kwargs: None,
    )
    first = client.get(f"/plans/{target_id}/suggestion", headers=headers).json()["suggestion"]
    assert first is not None
    saved = fake_store.suggestions[f"user-one:{target_id}"]
    saved["created_at"] = "2025-12-01T00:00:00+00:00"
    fake_store.plans[next(iter(fake_store.plans))]["latest_outcome"]["reported_at"] = "2026-01-01T00:00:00+00:00"
    mock_llm.complete.return_value = "Yeni sonuçlarına göre daha gerçekçi bir saat seçebilirsin."

    refreshed = client.get(f"/plans/{target_id}/suggestion", headers=headers).json()["suggestion"]
    assert refreshed is not None
    assert refreshed["message"] == mock_llm.complete.return_value
    assert refreshed != first
    assert mock_llm.complete.call_count == 2


@pytest.mark.parametrize("invalid_message", ["", "two lines\nnot allowed", "x" * 241])
def test_invalid_model_message_uses_validated_fallback(test_setup, monkeypatch, invalid_message):
    client, fake_store, mock_llm = test_setup
    headers = {"Authorization": f"Bearer {TOKEN_USER_ONE}"}
    mock_llm.complete.return_value = invalid_message
    now = datetime.now(timezone.utc)
    for days in (2, 3, 4):
        fake_store.add_plan(
            "user-one",
            planned_start=(now - timedelta(days=days, hours=2)).isoformat(),
            planned_end=(now - timedelta(days=days, hours=1)).isoformat(),
            latest_outcome={"status": "skipped"},
        )
    target_id = fake_store.add_plan("user-one")
    monkeypatch.setattr("app.services.weather.WeatherService.get_forecast", lambda *a, **kw: None)

    response = client.get(f"/plans/{target_id}/suggestion", headers=headers)
    suggestion = response.json()["suggestion"]
    assert response.status_code == 200
    assert suggestion["message"]
    assert len(suggestion["message"]) <= 240
    assert "\n" not in suggestion["message"]


def test_provider_failure_uses_deterministic_suggestion_fallback(test_setup, monkeypatch):
    from app.ai.llm import LLMError
    client, fake_store, mock_llm = test_setup
    mock_llm.complete.side_effect = LLMError("provider unavailable")
    now = datetime.now(timezone.utc)
    for days in (2, 3, 4):
        fake_store.add_plan("user-one", planned_start=(now - timedelta(days=days, hours=2)).isoformat(), planned_end=(now - timedelta(days=days, hours=1)).isoformat(), latest_outcome={"status": "skipped"})
    target = fake_store.add_plan("user-one")
    monkeypatch.setattr("app.services.weather.WeatherService.get_forecast", lambda *a, **kw: None)
    response = client.get(f"/plans/{target}/suggestion", headers={"Authorization": f"Bearer {TOKEN_USER_ONE}"})
    assert response.status_code == 200
    assert "uygun görünüyor" in response.json()["suggestion"]["message"]


def test_pattern_suggestion_generated_when_adherence_is_low(
    test_setup, monkeypatch: pytest.MonkeyPatch
):
    client, fake_store, mock_llm = test_setup
    headers = {"Authorization": f"Bearer {TOKEN_USER_ONE}"}

    # Keep this pattern-focused test independent of the live weather service.
    monkeypatch.setattr(
        "app.services.weather.WeatherService.get_forecast",
        lambda *args, **kwargs: None,
    )

    now = datetime.now(timezone.utc)
    # Three outcomes are the minimum history needed for personalization.
    fake_store.add_plan(
        "user-one",
        planned_start=(now - timedelta(days=2)).isoformat(),
        planned_end=(now - timedelta(days=2, hours=-1)).isoformat(),
        latest_outcome={"status": "done"},
    )
    fake_store.add_plan(
        "user-one",
        planned_start=(now - timedelta(days=1)).isoformat(),
        planned_end=(now - timedelta(days=1, hours=-1)).isoformat(),
        latest_outcome={"status": "skipped"},
    )
    fake_store.add_plan(
        "user-one",
        planned_start=(now - timedelta(days=3)).isoformat(),
        planned_end=(now - timedelta(days=3, hours=-1)).isoformat(),
        latest_outcome={"status": "skipped"},
    )

    target_plan_id = fake_store.add_plan(
        "user-one",
        title="Ders Çalışma",
        planned_start=(now + timedelta(hours=2)).isoformat(),
        planned_end=(now + timedelta(hours=3)).isoformat(),
    )

    resp = client.get(f"/plans/{target_plan_id}/suggestion", headers=headers)
    assert resp.status_code == 200
    data = resp.json()

    suggestion = data["suggestion"]
    assert suggestion is not None
    assert suggestion["plan_id"] == target_plan_id
    assert suggestion["reason"] == "pattern"
    assert suggestion["evidence"]["adherence_pct"] == 33.3
    assert suggestion["evidence"]["outcome_count"] == 3
    assert suggestion["evidence"].get("forecast") is None
    mock_llm.complete.assert_called_once()

    # Also verified saved in store
    assert fake_store.get_suggestion("user-one", target_plan_id) is not None


def test_no_suggestion_when_conditions_are_good(test_setup, monkeypatch: pytest.MonkeyPatch):
    client, fake_store, mock_llm = test_setup
    headers = {"Authorization": f"Bearer {TOKEN_USER_ONE}"}

    # Mock non-rainy weather
    from app.services.weather import HourlyForecast
    monkeypatch.setattr(
        "app.services.weather.WeatherService.get_forecast",
        lambda *args, **kwargs: HourlyForecast(
            time=datetime.now(timezone.utc),
            precipitation_probability=10.0,
            weather_code=0,
            is_rainy=False,
        ),
    )

    now = datetime.now(timezone.utc)
    # Historical plan with 100% adherence (done)
    fake_store.add_plan(
        "user-one",
        planned_start=(now - timedelta(days=1)).isoformat(),
        planned_end=(now - timedelta(days=1, hours=-1)).isoformat(),
        latest_outcome={"status": "done"},
    )

    target_plan_id = fake_store.add_plan(
        "user-one",
        title="Kitap Okuma",
        planned_start=(now + timedelta(hours=2)).isoformat(),
        planned_end=(now + timedelta(hours=3)).isoformat(),
    )

    resp = client.get(f"/plans/{target_plan_id}/suggestion", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["suggestion"] is None
    mock_llm.complete.assert_not_called()


def test_recommendation_frequency_off_suppresses_new_and_saved_suggestions(test_setup):
    client, fake_store, _ = test_setup
    plan_id = fake_store.add_plan("user-one")
    fake_store.personalization["user-one"] = {"recommendation_frequency": "off"}
    fake_store.suggestions[f"user-one:{plan_id}"] = {"plan_id": plan_id, "message": "Saved"}
    result = get_suggestion_for_plan(plan_id, AuthenticatedUser("user-one", "Europe/Istanbul", False, None), fake_store, MagicMock())
    assert result == {"suggestion": None}


def test_reset_profile_removes_frequency_preference_from_recommendation_logic(test_setup):
    client, fake_store, _ = test_setup
    plan_id = fake_store.add_plan("user-one")
    fake_store.personalization["user-one"] = {"recommendation_frequency": "off"}
    fake_store.suggestions[f"user-one:{plan_id}"] = {"plan_id": plan_id, "message": "Preserved suggestion"}
    fake_store.reset_personalization(user_id="user-one")
    result = get_suggestion_for_plan(plan_id, AuthenticatedUser("user-one", "Europe/Istanbul", False, None), fake_store, MagicMock())
    assert result["suggestion"]["message"] == "Preserved suggestion"


def test_weather_suggestion_generated_saved_and_retrieved_on_second_request(
    test_setup, monkeypatch: pytest.MonkeyPatch
):
    client, fake_store, mock_llm = test_setup
    headers = {"Authorization": f"Bearer {TOKEN_USER_ONE}"}

    from app.services.weather import DEFAULT_LATITUDE, DEFAULT_LONGITUDE, HourlyForecast
    target_time_dt = datetime.now(timezone.utc) + timedelta(hours=2)

    # Mock rainy weather forecast from Open-Meteo
    def mock_rainy_forecast(*args, **kwargs):
        assert kwargs.get("latitude") == DEFAULT_LATITUDE
        assert kwargs.get("longitude") == DEFAULT_LONGITUDE
        return HourlyForecast(
            time=target_time_dt,
            precipitation_probability=85.0,
            weather_code=61,  # Rain code
            is_rainy=True,
        )

    monkeypatch.setattr(
        "app.services.weather.WeatherService.get_forecast",
        mock_rainy_forecast,
    )

    for days_ago, outcome_status in ((1, "done"), (2, "skipped"), (3, "done")):
        fake_store.add_plan(
            "user-one",
            planned_start=(target_time_dt - timedelta(days=days_ago, hours=2)).isoformat(),
            planned_end=(target_time_dt - timedelta(days=days_ago, hours=1)).isoformat(),
            latest_outcome={"status": outcome_status},
        )

    target_plan_id = fake_store.add_plan(
        "user-one",
        title="Açık Hava Koşusu",
        planned_start=target_time_dt.isoformat(),
        planned_end=(target_time_dt + timedelta(hours=1)).isoformat(),
    )

    # 1. First request: generates weather suggestion and saves it
    resp1 = client.get(f"/plans/{target_plan_id}/suggestion", headers=headers)
    assert resp1.status_code == 200
    data1 = resp1.json()
    suggestion1 = data1["suggestion"]
    assert suggestion1 is not None
    assert suggestion1["plan_id"] == target_plan_id
    assert suggestion1["reason"] == "weather"
    assert suggestion1["evidence"]["forecast"] == "rain"
    assert "proposed_start" in suggestion1
    assert "proposed_end" in suggestion1
    mock_llm.complete.assert_called_once()

    # Verify saved in store
    saved_in_store = fake_store.get_suggestion("user-one", target_plan_id)
    assert saved_in_store is not None
    assert saved_in_store["reason"] == "weather"

    # 2. Second request: returns saved suggestion without re-calling LLM or changing data
    mock_llm.reset_mock()
    resp2 = client.get(f"/plans/{target_plan_id}/suggestion", headers=headers)
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["suggestion"] == suggestion1
    mock_llm.complete.assert_not_called()


def test_weather_service_failure_is_handled_safely(test_setup, monkeypatch: pytest.MonkeyPatch):
    client, fake_store, _ = test_setup
    headers = {"Authorization": f"Bearer {TOKEN_USER_ONE}"}

    # Simulate WeatherService raising an unexpected exception
    def broken_get_forecast(*args, **kwargs):
        raise RuntimeError("Open-Meteo connection timeout or DNS error")

    monkeypatch.setattr(
        "app.services.weather.WeatherService.get_forecast",
        broken_get_forecast,
    )

    target_plan_id = fake_store.add_plan("user-one")
    # Must not raise 500 error; gracefully handle weather failure
    resp = client.get(f"/plans/{target_plan_id}/suggestion", headers=headers)
    assert resp.status_code == 200


def test_proposed_start_is_strictly_in_the_future_for_past_plans(test_setup):
    client, fake_store, _ = test_setup
    headers = {"Authorization": f"Bearer {TOKEN_USER_ONE}"}

    now = datetime.now(timezone.utc)
    # Three skipped outcomes meet the minimum history and trigger a pattern suggestion.
    for days in (10, 11, 12):
        fake_store.add_plan(
            "user-one",
            planned_start=(now - timedelta(days=days)).isoformat(),
            planned_end=(now - timedelta(days=days, hours=-1)).isoformat(),
            latest_outcome={"status": "skipped"},
        )

    # An old plan from 5 days ago
    past_plan_id = fake_store.add_plan(
        "user-one",
        title="Eski Koşu Planı",
        planned_start=(now - timedelta(days=5)).isoformat(),
        planned_end=(now - timedelta(days=5, hours=-1)).isoformat(),
    )

    resp = client.get(f"/plans/{past_plan_id}/suggestion", headers=headers)
    assert resp.status_code == 200
    suggestion = resp.json()["suggestion"]
    assert suggestion is not None

    proposed_start = datetime.fromisoformat(suggestion["proposed_start"])
    # Proposed start must strictly be after current time
    assert proposed_start > now
