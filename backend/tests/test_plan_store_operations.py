from __future__ import annotations

import json
from datetime import datetime

import httpx

from app.db.plans import SupabasePlanStore


def _store(handler) -> SupabasePlanStore:
    store = SupabasePlanStore("https://example.invalid", "service-key")
    headers = dict(store._client.headers)
    store._client.close()
    store._client = httpx.Client(
        transport=httpx.MockTransport(handler), headers=headers
    )
    return store


def test_list_plans_scopes_dates_and_selects_deterministic_latest_outcome() -> None:
    latest = {
        "id": "outcome-new",
        "status": "done",
        "actual_start": "2026-10-15T18:40:00+03:00",
        "postponed_to": None,
        "note": None,
        "reported_via": "web",
        "reported_at": "2026-10-15T18:45:00+03:00",
    }
    params_seen = None

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal params_seen
        params_seen = dict(request.url.params)
        return httpx.Response(
            200,
            json=[
                {
                    "id": "plan-one",
                    "title": "Run",
                    "category": "sport",
                    "planned_start": "2026-10-15T18:30:00+03:00",
                    "planned_end": "2026-10-15T19:30:00+03:00",
                    "recurrence_rule": None,
                    "source": "text",
                    "created_at": "2026-10-14T10:00:00+03:00",
                    "outcomes": [latest],
                },
                {
                    "id": "plan-two",
                    "title": "Study",
                    "category": "study",
                    "planned_start": "2026-10-16T10:00:00+03:00",
                    "planned_end": "2026-10-16T11:00:00+03:00",
                    "recurrence_rule": None,
                    "source": "text",
                    "created_at": "2026-10-14T10:00:00+03:00",
                    "outcomes": [],
                },
            ],
            request=request,
        )

    store = _store(handle)
    try:
        result = store.list_plans(
            user_id="user-one",
            from_time=datetime.fromisoformat("2026-10-15T00:00:00+03:00"),
            to_time=datetime.fromisoformat("2026-10-16T23:59:59+03:00"),
        )
    finally:
        store._client.close()

    assert params_seen is not None
    assert params_seen["user_id"] == "eq.user-one"
    assert params_seen["and"] == (
        "(planned_start.gte.2026-10-15T00:00:00+03:00,"
        "planned_start.lte.2026-10-16T23:59:59+03:00)"
    )
    assert params_seen["order"] == "planned_start.asc,id.asc"
    assert params_seen["outcomes.order"] == "reported_at.desc,id.desc"
    assert params_seen["outcomes.limit"] == "1"
    assert result[0]["latest_outcome"] == latest
    assert result[1]["latest_outcome"] is None


def test_get_plan_requires_both_plan_and_authenticated_owner() -> None:
    captured: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json=[], request=request)

    store = _store(handle)
    try:
        result = store.get_plan(user_id="user-one", plan_id="plan-two")
    finally:
        store._client.close()

    assert result is None
    assert len(captured) == 1
    assert captured[0].url.params["id"] == "eq.plan-two"
    assert captured[0].url.params["user_id"] == "eq.user-one"
    assert captured[0].url.params["limit"] == "1"


def test_create_outcome_uses_authenticated_owner_and_appends_each_event() -> None:
    saved_rows = [
        {
            "id": "outcome-one",
            "plan_id": "plan-one",
            "user_id": "user-one",
            "status": "postponed",
            "actual_start": None,
            "postponed_to": None,
            "note": None,
            "reported_via": "device",
            "reported_at": "2026-10-15T18:30:00+03:00",
        },
        {
            "id": "outcome-two",
            "plan_id": "plan-one",
            "user_id": "user-one",
            "status": "done",
            "actual_start": "2026-10-15T19:00:00+03:00",
            "postponed_to": None,
            "note": None,
            "reported_via": "web",
            "reported_at": "2026-10-15T19:05:00+03:00",
        },
    ]
    sent: list[dict[str, object]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.headers["Prefer"] == "return=representation"
        body = json.loads(request.content)
        sent.append(body)
        return httpx.Response(201, json=[saved_rows[len(sent) - 1]], request=request)

    store = _store(handle)
    payloads = [
        {"status": "postponed", "reported_via": "device", "user_id": "attacker"},
        {"status": "done", "reported_via": "web", "plan_id": "other-plan"},
    ]
    try:
        first = store.create_outcome(
            user_id="user-one", plan_id="plan-one", outcome=payloads[0]
        )
        second = store.create_outcome(
            user_id="user-one", plan_id="plan-one", outcome=payloads[1]
        )
    finally:
        store._client.close()

    assert [first["id"], second["id"]] == ["outcome-one", "outcome-two"]
    assert [row["status"] for row in sent] == ["postponed", "done"]
    assert all(row["user_id"] == "user-one" for row in sent)
    assert all(row["plan_id"] == "plan-one" for row in sent)
