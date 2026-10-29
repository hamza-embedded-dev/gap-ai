from __future__ import annotations

import hashlib
import json
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.analytics.insights import (
    calculate_recommendations,
    calculate_insights,
    get_period_window,
    parse_timestamp,
)
from app.api.errors import APIError
from app.api.insights import InsightsResponse, get_insights
from app.api.upcoming import get_system_time
from app.db.plans import AuthenticatedUser, get_plan_store
from app.main import app


def test_behavior_recommendations_require_three_distinct_reported_plans_and_include_evidence():
    plans = []
    outcomes = []
    for index in range(3):
        pid = f"p{index}"
        plans.append({"id": pid, "category": "sport", "planned_start": f"2026-10-0{index + 1}T18:00:00+03:00"})
        outcomes.append({"id": f"o{index}", "plan_id": pid, "status": "skipped", "reported_at": f"2026-10-0{index + 1}T19:00:00+03:00"})
    recommendations = calculate_recommendations(plans, outcomes, user_timezone="Europe/Istanbul")
    assert recommendations[0]["id"] == "missed-category"
    assert recommendations[0]["evidence"]["count"] == 3
    assert recommendations[0]["evidence"]["sample_size"] == 3
    assert len(calculate_recommendations(plans[:2], outcomes[:2], user_timezone="Europe/Istanbul")) == 0
    assert calculate_recommendations([], [], user_timezone="Europe/Istanbul") == []

PEPPER = "p" * 32
TOKEN_USER_A = "token-user-a"
TOKEN_USER_B = "token-user-b"
HASH_USER_A = hashlib.sha256((TOKEN_USER_A + PEPPER).encode("utf-8")).hexdigest()
HASH_USER_B = hashlib.sha256((TOKEN_USER_B + PEPPER).encode("utf-8")).hexdigest()

TZ_ISTANBUL = ZoneInfo("Europe/Istanbul")
FIXED_NOW = datetime(2026, 10, 18, 23, 59, 59, tzinfo=TZ_ISTANBUL)


class FakeInsightsStore:
    def __init__(self) -> None:
        self.plans: dict[str, dict[str, object]] = {}
        self.plan_owners: dict[str, str] = {}
        self.outcomes: dict[str, dict[str, object]] = {}
        self.tokens: dict[str, tuple[AuthenticatedUser, str | None]] = {}
        self.personalization: dict[str, dict[str, object]] = {}

    def get_user_for_token_hash(self, token_hash: str):
        return self.tokens.get(token_hash)

    def get_personalization(self, *, user_id: str):
        return self.personalization.get(user_id, {})

    def add_plan(
        self,
        *,
        user_id: str,
        title: str,
        start: datetime,
        category: str = "sport",
        duration_minutes: int = 60,
    ) -> dict[str, object]:
        plan_id = str(uuid4())
        start_iso = start.isoformat()
        end_iso = (start + timedelta(minutes=duration_minutes)).isoformat()
        plan = {
            "id": plan_id,
            "user_id": user_id,
            "title": title,
            "category": category,
            "planned_start": start_iso,
            "planned_end": end_iso,
            "recurrence_rule": None,
            "source": "web",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "latest_outcome": None,
        }
        self.plans[plan_id] = plan
        self.plan_owners[plan_id] = user_id
        return plan

    def add_outcome(
        self,
        *,
        plan_id: str,
        user_id: str,
        status: str,
        actual_start: datetime | None = None,
        postponed_to: datetime | None = None,
        reported_at: datetime | None = None,
    ) -> dict[str, object]:
        outcome_id = str(uuid4())
        outcome = {
            "id": outcome_id,
            "plan_id": plan_id,
            "user_id": user_id,
            "status": status,
            "actual_start": actual_start.isoformat() if actual_start else None,
            "postponed_to": postponed_to.isoformat() if postponed_to else None,
            "note": None,
            "reported_via": "web",
            "reported_at": (
                reported_at.isoformat()
                if reported_at
                else datetime.now(timezone.utc).isoformat()
            ),
        }
        self.outcomes[outcome_id] = outcome
        # Update latest_outcome on plan
        if plan_id in self.plans:
            self.plans[plan_id]["latest_outcome"] = outcome
        return outcome

    def list_plans(
        self,
        *,
        user_id: str,
        from_: datetime | None = None,
        to: datetime | None = None,
        from_time: datetime | None = None,
        to_time: datetime | None = None,
    ) -> list[dict[str, object]]:
        effective_from = from_ if from_ is not None else from_time
        effective_to = to if to is not None else to_time
        matching: list[dict[str, object]] = []

        for plan_id, snapshot in self.plans.items():
            if self.plan_owners.get(plan_id) != user_id:
                continue
            start_dt = datetime.fromisoformat(
                str(snapshot["planned_start"]).replace("Z", "+00:00")
            )
            if effective_from is not None:
                norm_from = (
                    effective_from
                    if effective_from.tzinfo
                    else effective_from.replace(tzinfo=start_dt.tzinfo)
                )
                if start_dt < norm_from:
                    continue
            if effective_to is not None:
                norm_to = (
                    effective_to
                    if effective_to.tzinfo
                    else effective_to.replace(tzinfo=start_dt.tzinfo)
                )
                if start_dt > norm_to:
                    continue
            matching.append(snapshot)

        matching.sort(
            key=lambda p: datetime.fromisoformat(str(p["planned_start"]).replace("Z", "+00:00"))
        )
        return matching

    def list_outcomes(self, *, user_id: str) -> list[dict[str, object]]:
        return [
            o for o in self.outcomes.values() if o.get("user_id") == user_id
        ]


# ==============================================================================
# 1. PURE ENGINE UNIT TESTS (calculate_insights)
# ==============================================================================

def test_insights_engine_cold_start() -> None:
    result = calculate_insights(
        plans=[],
        outcomes=[],
        period="week",
        reference_time=FIXED_NOW,
        user_timezone="Europe/Istanbul",
        is_demo=False,
    )
    assert result["planned"] == 0
    assert result["done"] == 0
    assert result["postponed"] == 0
    assert result["skipped"] == 0
    assert result["unreported"] == 0
    assert result["adherence_pct"] is None
    assert result["avg_start_delay_min"] is None
    assert result["by_weekday"] == {}
    assert result["by_hour"] == {}
    assert result["by_category"] == {}
    assert result["postponed_targets"] == []
    assert result["trend_vs_prev"] is None
    assert result["narrative"] is None
    assert result["is_demo"] is False
    assert result["data_label"] == "real"


def test_insights_engine_unreported_plans_only() -> None:
    plans = [
        {
            "id": "p1",
            "title": "Workout",
            "category": "sport",
            "planned_start": "2026-10-13T08:00:00+03:00",
            "planned_end": "2026-10-13T09:00:00+03:00",
        },
        {
            "id": "p2",
            "title": "Study",
            "category": "study",
            "planned_start": "2026-10-14T10:00:00+03:00",
            "planned_end": "2026-10-14T11:00:00+03:00",
        },
    ]
    result = calculate_insights(
        plans=plans,
        outcomes=[],
        period="week",
        reference_time=FIXED_NOW,
        user_timezone="Europe/Istanbul",
    )
    assert result["planned"] == 2
    assert result["done"] == 0
    assert result["postponed"] == 0
    assert result["skipped"] == 0
    assert result["unreported"] == 2
    assert result["adherence_pct"] is None
    assert result["avg_start_delay_min"] is None
    # Invariant: planned == done + postponed + skipped + unreported
    assert result["planned"] == (
        result["done"] + result["postponed"] + result["skipped"] + result["unreported"]
    )


def test_insights_engine_single_done_with_delay() -> None:
    plans = [
        {
            "id": "p1",
            "title": "Gym",
            "category": "sport",
            "planned_start": "2026-10-12T18:00:00+03:00",
            "planned_end": "2026-10-12T19:00:00+03:00",
        }
    ]
    outcomes = [
        {
            "id": "o1",
            "plan_id": "p1",
            "status": "done",
            "actual_start": "2026-10-12T18:15:00+03:00",
            "reported_at": "2026-10-12T19:05:00+03:00",
        }
    ]
    result = calculate_insights(
        plans=plans,
        outcomes=outcomes,
        period="week",
        reference_time=FIXED_NOW,
        user_timezone="Europe/Istanbul",
    )
    assert result["planned"] == 1
    assert result["done"] == 1
    assert result["unreported"] == 0
    assert result["adherence_pct"] == 100.0
    assert result["avg_start_delay_min"] == 15
    assert result["by_weekday"] == {"Monday": {"planned": 1, "done": 1, "postponed": 0}}
    assert result["by_hour"] == {"18": {"planned": 1, "done": 1}}
    assert result["by_category"] == {"sport": {"planned": 1, "done": 1}}


def test_insights_engine_latest_outcome_tie_breaker() -> None:
    plans = [
        {
            "id": "p1",
            "title": "Code",
            "category": "work",
            "planned_start": "2026-10-13T14:00:00+03:00",
            "planned_end": "2026-10-13T15:00:00+03:00",
        }
    ]
    # Two outcomes at identical reported_at timestamps. Tie-breaker is id DESC.
    outcomes = [
        {
            "id": "outcome-a",
            "plan_id": "p1",
            "status": "skipped",
            "reported_at": "2026-10-13T15:05:00+03:00",
        },
        {
            "id": "outcome-z",
            "plan_id": "p1",
            "status": "done",
            "actual_start": "2026-10-13T14:00:00+03:00",
            "reported_at": "2026-10-13T15:05:00+03:00",
        },
    ]
    result = calculate_insights(
        plans=plans,
        outcomes=outcomes,
        period="week",
        reference_time=FIXED_NOW,
        user_timezone="Europe/Istanbul",
    )
    # outcome-z > outcome-a, so status is "done"
    assert result["done"] == 1
    assert result["skipped"] == 0
    assert result["adherence_pct"] == 100.0


def test_insights_engine_zero_adherence_not_null() -> None:
    plans = [
        {
            "id": "p1",
            "title": "T1",
            "category": "work",
            "planned_start": "2026-10-13T10:00:00+03:00",
            "planned_end": "2026-10-13T11:00:00+03:00",
        },
        {
            "id": "p2",
            "title": "T2",
            "category": "work",
            "planned_start": "2026-10-14T10:00:00+03:00",
            "planned_end": "2026-10-14T11:00:00+03:00",
        },
    ]
    outcomes = [
        {"id": "o1", "plan_id": "p1", "status": "postponed", "reported_at": "2026-10-13T10:05:00+03:00"},
        {"id": "o2", "plan_id": "p2", "status": "skipped", "reported_at": "2026-10-14T10:05:00+03:00"},
    ]
    result = calculate_insights(
        plans=plans,
        outcomes=outcomes,
        period="week",
        reference_time=FIXED_NOW,
        user_timezone="Europe/Istanbul",
    )
    assert result["planned"] == 2
    assert result["done"] == 0
    assert result["postponed"] == 1
    assert result["skipped"] == 1
    assert result["unreported"] == 0
    # Denominator is 2, done is 0 -> 0.0 (NOT None)
    assert result["adherence_pct"] == 0.0
    assert result["avg_start_delay_min"] is None


def test_insights_engine_postponed_targets_sorting() -> None:
    outcomes = [
        {"id": "o1", "status": "postponed", "postponed_to": "2026-10-15T19:00:00+03:00"},  # Thursday 19:00
        {"id": "o2", "status": "postponed", "postponed_to": "2026-10-13T10:00:00+03:00"},  # Tuesday 10:00
        {"id": "o3", "status": "postponed", "postponed_to": "2026-10-15T10:00:00+03:00"},  # Thursday 10:00
        {"id": "o4", "status": "postponed", "postponed_to": "2026-10-13T10:00:00+03:00"},  # Tuesday 10:00 (repeat)
        {"id": "o5", "status": "postponed", "postponed_to": None},  # No target time
        {"id": "o6", "status": "done", "postponed_to": "2026-10-16T15:00:00+03:00"},  # done status, not postponed
    ]
    result = calculate_insights(
        plans=[],
        outcomes=outcomes,
        period="all",
        reference_time=FIXED_NOW,
        user_timezone="Europe/Istanbul",
    )
    targets = result["postponed_targets"]
    assert len(targets) == 3
    # Ordered by weekday index (Tuesday before Thursday), then hour
    assert targets[0] == {"weekday": "Tuesday", "hour": 10, "count": 2}
    assert targets[1] == {"weekday": "Thursday", "hour": 10, "count": 1}
    assert targets[2] == {"weekday": "Thursday", "hour": 19, "count": 1}


def test_insights_engine_requires_explicit_reference_time() -> None:
    with pytest.raises(ValueError, match="reference_time must be explicitly provided"):
        calculate_insights(
            plans=[],
            outcomes=[],
            period="week",
            reference_time=None,  # type: ignore[arg-type]
        )


def test_insights_engine_invalid_timezone() -> None:
    with pytest.raises(ValueError, match="Invalid timezone"):
        calculate_insights(
            plans=[],
            outcomes=[],
            period="week",
            reference_time=FIXED_NOW,
            user_timezone="Invalid/Zone",
        )


# ==============================================================================
# 2. K-8 TIME BOUNDARY & PERIOD TESTS
# ==============================================================================

def test_k8_period_window_calculation() -> None:
    # 2026-10-15 is Thursday
    thursday = datetime(2026, 10, 15, 14, 30, tzinfo=TZ_ISTANBUL)

    # week window
    w_start, w_end = get_period_window("week", thursday, TZ_ISTANBUL)
    assert w_start == datetime(2026, 10, 12, 0, 0, 0, 0, tzinfo=TZ_ISTANBUL)
    assert w_end == datetime(2026, 10, 18, 23, 59, 59, 999999, tzinfo=TZ_ISTANBUL)

    # last_week window
    lw_start, lw_end = get_period_window("last_week", thursday, TZ_ISTANBUL)
    assert lw_start == datetime(2026, 10, 5, 0, 0, 0, 0, tzinfo=TZ_ISTANBUL)
    assert lw_end == datetime(2026, 10, 11, 23, 59, 59, 999999, tzinfo=TZ_ISTANBUL)

    # all window
    all_start, all_end = get_period_window("all", thursday, TZ_ISTANBUL)
    assert all_start is None
    assert all_end is None


def test_k8_period_filtering_week_vs_last_week() -> None:
    # Plan in last week (Oct 8) and plan in this week (Oct 14)
    plans = [
        {
            "id": "p_last_week",
            "title": "Last Week Plan",
            "category": "work",
            "planned_start": "2026-10-08T10:00:00+03:00",
            "planned_end": "2026-10-08T11:00:00+03:00",
        },
        {
            "id": "p_this_week",
            "title": "This Week Plan",
            "category": "sport",
            "planned_start": "2026-10-14T10:00:00+03:00",
            "planned_end": "2026-10-14T11:00:00+03:00",
        },
    ]

    # Query week
    res_week = calculate_insights(plans, [], "week", FIXED_NOW, "Europe/Istanbul")
    assert res_week["planned"] == 1
    assert "sport" in res_week["by_category"]
    assert "work" not in res_week["by_category"]

    # Query last_week
    res_last = calculate_insights(plans, [], "last_week", FIXED_NOW, "Europe/Istanbul")
    assert res_last["planned"] == 1
    assert "work" in res_last["by_category"]
    assert "sport" not in res_last["by_category"]

    # Query all
    res_all = calculate_insights(plans, [], "all", FIXED_NOW, "Europe/Istanbul")
    assert res_all["planned"] == 2
    assert "work" in res_all["by_category"]
    assert "sport" in res_all["by_category"]


def test_k8_future_plans_excluded() -> None:
    # Reference time is Wednesday 12:00
    ref = datetime(2026, 10, 14, 12, 0, 0, tzinfo=TZ_ISTANBUL)
    plans = [
        {
            "id": "p_past",
            "title": "Past",
            "category": "sport",
            "planned_start": "2026-10-13T10:00:00+03:00",
            "planned_end": "2026-10-13T11:00:00+03:00",
        },
        {
            "id": "p_future",
            "title": "Future",
            "category": "sport",
            "planned_start": "2026-10-15T10:00:00+03:00",  # Starts after ref
            "planned_end": "2026-10-15T11:00:00+03:00",
        },
    ]
    res = calculate_insights(plans, [], "week", ref, "Europe/Istanbul")
    # Only past plan should be evaluated
    assert res["planned"] == 1
    assert res["unreported"] == 1
    assert res["planned"] == (res["done"] + res["postponed"] + res["skipped"] + res["unreported"])


# ==============================================================================
# 3. V1-3 ACCEPTANCE FIXTURE TESTS (Direct against calculate_insights)
# ==============================================================================

FIXTURES_PATH = Path(__file__).parent / "fixtures" / "insights_cases.json"


def _load_v1_cases():
    assert FIXTURES_PATH.exists(), f"V1-3 fixture file not found at {FIXTURES_PATH}"
    with open(FIXTURES_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data["cases"], data.get("reference_timezone", "Europe/Istanbul")


V1_CASES, DEFAULT_TZ = _load_v1_cases()


@pytest.mark.parametrize("case", V1_CASES, ids=lambda c: c["id"])
def test_v1_3_acceptance_fixture_case(case: dict[str, object]) -> None:
    """Verifies that calculate_insights passes each hand-crafted V1-3 fixture case."""
    inputs = case["inputs"]  # type: ignore[index]
    expected = case["expected"]  # type: ignore[index]

    actual = calculate_insights(
        plans=inputs.get("plans", []),
        outcomes=inputs.get("outcomes", []),
        period=str(case.get("period", "week")),
        reference_time=datetime.fromisoformat(str(case["reference_time"])),
        user_timezone=DEFAULT_TZ,
        is_demo=False,
    )

    assert actual == expected, (
        f"Fixture case {case['id']} mismatch!\n"
        f"Actual: {json.dumps(actual, indent=2)}\n"
        f"Expected: {json.dumps(expected, indent=2)}"
    )


# ==============================================================================
# 4. API ROUTE & SECURITY TESTS (GET /insights)
# ==============================================================================

def test_api_insights_unauthorized_no_token() -> None:
    client = TestClient(app)
    response = client.get("/insights")
    assert response.status_code == 401
    assert response.json()["error"] == "unauthorized"


def test_api_insights_unauthorized_invalid_token() -> None:
    fake_store = FakeInsightsStore()
    app.dependency_overrides[get_plan_store] = lambda: fake_store
    app.dependency_overrides[get_system_time] = lambda: FIXED_NOW
    try:
        client = TestClient(app)
        response = client.get("/insights", headers={"Authorization": "Bearer invalid-token"})
        assert response.status_code == 401
        assert response.json()["error"] == "unauthorized"
    finally:
        app.dependency_overrides.clear()


def test_api_insights_unauthorized_expired_token(monkeypatch) -> None:
    settings = SimpleNamespace(
        token_hash_pepper=SecretStr(PEPPER),
        allowed_origins=[],
        supabase_url=None,
        supabase_service_key=None,
    )
    monkeypatch.setattr("app.api.plans.get_settings", lambda: settings)

    fake_store = FakeInsightsStore()
    expired_user = AuthenticatedUser("u-exp", "Europe/Istanbul", False, None)
    # Token expired yesterday
    past_iso = (FIXED_NOW - timedelta(days=1)).isoformat()
    fake_store.tokens[HASH_USER_A] = (expired_user, past_iso)

    app.dependency_overrides[get_plan_store] = lambda: fake_store
    app.dependency_overrides[get_system_time] = lambda: FIXED_NOW
    try:
        client = TestClient(app)
        response = client.get("/insights", headers={"Authorization": f"Bearer {TOKEN_USER_A}"})
        assert response.status_code == 401
        assert response.json()["error"] == "unauthorized"
    finally:
        app.dependency_overrides.clear()


def test_api_insights_validation_error_invalid_period(monkeypatch) -> None:
    settings = SimpleNamespace(
        token_hash_pepper=SecretStr(PEPPER),
        allowed_origins=[],
        supabase_url=None,
        supabase_service_key=None,
    )
    monkeypatch.setattr("app.api.plans.get_settings", lambda: settings)

    fake_store = FakeInsightsStore()
    user = AuthenticatedUser("u-valid", "Europe/Istanbul", False, None)
    fake_store.tokens[HASH_USER_A] = (user, None)

    app.dependency_overrides[get_plan_store] = lambda: fake_store
    app.dependency_overrides[get_system_time] = lambda: FIXED_NOW
    try:
        client = TestClient(app)
        response = client.get(
            "/insights?period=yearly",
            headers={"Authorization": f"Bearer {TOKEN_USER_A}"},
        )
        assert response.status_code == 422
        assert response.json()["error"] == "validation_error"
    finally:
        app.dependency_overrides.clear()


def test_api_insights_validation_error_invalid_timezone(monkeypatch) -> None:
    settings = SimpleNamespace(
        token_hash_pepper=SecretStr(PEPPER),
        allowed_origins=[],
        supabase_url=None,
        supabase_service_key=None,
    )
    monkeypatch.setattr("app.api.plans.get_settings", lambda: settings)

    fake_store = FakeInsightsStore()
    user = AuthenticatedUser("u-invalid-tz", "Bad/Timezone", False, None)
    fake_store.tokens[HASH_USER_A] = (user, None)

    app.dependency_overrides[get_plan_store] = lambda: fake_store
    app.dependency_overrides[get_system_time] = lambda: FIXED_NOW
    try:
        client = TestClient(app)
        response = client.get("/insights", headers={"Authorization": f"Bearer {TOKEN_USER_A}"})
        assert response.status_code == 422
        assert response.json()["error"] == "validation_error"
    finally:
        app.dependency_overrides.clear()


def test_api_insights_user_isolation(monkeypatch) -> None:
    settings = SimpleNamespace(
        token_hash_pepper=SecretStr(PEPPER),
        allowed_origins=[],
        supabase_url=None,
        supabase_service_key=None,
    )
    monkeypatch.setattr("app.api.plans.get_settings", lambda: settings)

    fake_store = FakeInsightsStore()
    user_a = AuthenticatedUser("user-a", "Europe/Istanbul", False, None)
    user_b = AuthenticatedUser("user-b", "Europe/Istanbul", False, None)
    fake_store.tokens[HASH_USER_A] = (user_a, None)
    fake_store.tokens[HASH_USER_B] = (user_b, None)

    # User A has 2 plans (1 done, 1 postponed)
    p_a1 = fake_store.add_plan(user_id="user-a", title="Plan A1", start=datetime(2026, 10, 13, 10, 0, tzinfo=TZ_ISTANBUL))
    p_a2 = fake_store.add_plan(user_id="user-a", title="Plan A2", start=datetime(2026, 10, 14, 10, 0, tzinfo=TZ_ISTANBUL))
    fake_store.add_outcome(plan_id=str(p_a1["id"]), user_id="user-a", status="done", actual_start=datetime(2026, 10, 13, 10, 0, tzinfo=TZ_ISTANBUL))
    fake_store.add_outcome(plan_id=str(p_a2["id"]), user_id="user-a", status="postponed", postponed_to=datetime(2026, 10, 15, 19, 0, tzinfo=TZ_ISTANBUL))

    # User B has 1 plan (skipped)
    p_b1 = fake_store.add_plan(user_id="user-b", title="Plan B1", start=datetime(2026, 10, 13, 11, 0, tzinfo=TZ_ISTANBUL))
    fake_store.add_outcome(plan_id=str(p_b1["id"]), user_id="user-b", status="skipped")

    app.dependency_overrides[get_plan_store] = lambda: fake_store
    app.dependency_overrides[get_system_time] = lambda: FIXED_NOW
    try:
        client = TestClient(app)

        # Request as User A
        resp_a = client.get("/insights", headers={"Authorization": f"Bearer {TOKEN_USER_A}"})
        assert resp_a.status_code == 200
        data_a = resp_a.json()
        assert data_a["planned"] == 2
        assert data_a["done"] == 1
        assert data_a["postponed"] == 1
        assert data_a["skipped"] == 0
        assert data_a["adherence_pct"] == 50.0
        assert len(data_a["postponed_targets"]) == 1

        # Request as User B
        resp_b = client.get("/insights", headers={"Authorization": f"Bearer {TOKEN_USER_B}"})
        assert resp_b.status_code == 200
        data_b = resp_b.json()
        assert data_b["planned"] == 1
        assert data_b["done"] == 0
        assert data_b["postponed"] == 0
        assert data_b["skipped"] == 1
        assert data_b["adherence_pct"] == 0.0
        assert len(data_b["postponed_targets"]) == 0
    finally:
        app.dependency_overrides.clear()


def test_api_insights_demo_mode_flags(monkeypatch) -> None:
    settings = SimpleNamespace(
        token_hash_pepper=SecretStr(PEPPER),
        allowed_origins=[],
        supabase_url=None,
        supabase_service_key=None,
    )
    monkeypatch.setattr("app.api.plans.get_settings", lambda: settings)

    fake_store = FakeInsightsStore()
    demo_expiry = (FIXED_NOW + timedelta(hours=12)).isoformat()
    demo_user = AuthenticatedUser("demo-user", "Europe/Istanbul", True, demo_expiry)
    fake_store.tokens[HASH_USER_A] = (demo_user, None)

    app.dependency_overrides[get_plan_store] = lambda: fake_store
    monkeypatch.setattr("app.api.plans.get_system_time", lambda: FIXED_NOW)
    try:
        client = TestClient(app)
        response = client.get("/insights", headers={"Authorization": f"Bearer {TOKEN_USER_A}"})
        assert response.status_code == 200
        data = response.json()
        assert data["is_demo"] is True
        assert data["data_label"] == "demo"
    finally:
        app.dependency_overrides.clear()


def test_api_insights_not_implemented_store_error() -> None:
    class StoreWithoutListPlans:
        def get_user_for_token_hash(self, token_hash: str):
            return None

    user = AuthenticatedUser("u1", "Europe/Istanbul", False, None)
    with pytest.raises(NotImplementedError, match="PlanStore implementation does not support list_plans yet"):
        get_insights(user=user, store=StoreWithoutListPlans(), period="week", current_time=FIXED_NOW)  # type: ignore[arg-type]


def test_api_insights_missing_list_outcomes_raises_not_implemented_even_with_latest_outcome() -> None:
    # A store that has list_plans and provides latest_outcome on plans,
    # but does NOT have list_outcomes.
    class StoreWithoutListOutcomes:
        def get_user_for_token_hash(self, token_hash: str):
            return None

        def list_plans(self, *args, **kwargs):
            return [
                {
                    "id": "p1",
                    "title": "Workout",
                    "category": "sport",
                    "planned_start": "2026-10-13T10:00:00+03:00",
                    "planned_end": "2026-10-13T11:00:00+03:00",
                    "latest_outcome": {
                        "id": "o2",
                        "status": "done",
                        "actual_start": "2026-10-13T10:00:00+03:00",
                    },
                }
            ]

    user = AuthenticatedUser("u1", "Europe/Istanbul", False, None)
    # Must NOT silently fall back to latest_outcome and produce incomplete results; must raise NotImplementedError!
    with pytest.raises(NotImplementedError, match="PlanStore implementation does not support list_outcomes yet"):
        get_insights(user=user, store=StoreWithoutListOutcomes(), period="week", current_time=FIXED_NOW)  # type: ignore[arg-type]


def test_api_insights_intermediate_postponement_included_in_postponed_targets(monkeypatch) -> None:
    settings = SimpleNamespace(
        token_hash_pepper=SecretStr(PEPPER),
        allowed_origins=[],
        supabase_url=None,
        supabase_service_key=None,
    )
    monkeypatch.setattr("app.api.plans.get_settings", lambda: settings)

    fake_store = FakeInsightsStore()
    user = AuthenticatedUser("u-postpone", "Europe/Istanbul", False, None)
    fake_store.tokens[HASH_USER_A] = (user, None)

    # Plan on Tuesday 14:00
    plan = fake_store.add_plan(
        user_id="u-postpone",
        title="Study",
        category="study",
        start=datetime(2026, 10, 13, 14, 0, tzinfo=TZ_ISTANBUL),
    )
    plan_id = str(plan["id"])

    # 1. First outcome: postponed to Thursday 19:00
    fake_store.add_outcome(
        plan_id=plan_id,
        user_id="u-postpone",
        status="postponed",
        postponed_to=datetime(2026, 10, 15, 19, 0, tzinfo=TZ_ISTANBUL),
        reported_at=datetime(2026, 10, 13, 14, 5, tzinfo=TZ_ISTANBUL),
    )

    # 2. Second outcome: done reported later at 15:35
    fake_store.add_outcome(
        plan_id=plan_id,
        user_id="u-postpone",
        status="done",
        actual_start=datetime(2026, 10, 13, 14, 0, tzinfo=TZ_ISTANBUL),
        reported_at=datetime(2026, 10, 13, 15, 35, tzinfo=TZ_ISTANBUL),
    )

    app.dependency_overrides[get_plan_store] = lambda: fake_store
    app.dependency_overrides[get_system_time] = lambda: FIXED_NOW
    try:
        client = TestClient(app)
        response = client.get("/insights", headers={"Authorization": f"Bearer {TOKEN_USER_A}"})
        assert response.status_code == 200
        data = response.json()

        # Latest outcome is done -> adherence 100%
        assert data["planned"] == 1
        assert data["done"] == 1
        assert data["postponed"] == 0
        assert data["adherence_pct"] == 100.0

        # But intermediate postponement IS captured in postponed_targets!
        assert len(data["postponed_targets"]) == 1
        assert data["postponed_targets"][0] == {
            "weekday": "Thursday",
            "hour": 19,
            "count": 1,
        }
    finally:
        app.dependency_overrides.clear()


def test_api_insights_pydantic_schema_extra_forbid() -> None:
    # Validate that InsightsResponse rejects extra fields
    payload = {
        "period": "week",
        "planned": 1,
        "done": 1,
        "postponed": 0,
        "skipped": 0,
        "unreported": 0,
        "adherence_pct": 100.0,
        "avg_start_delay_min": 10,
        "by_weekday": {"Monday": {"planned": 1, "done": 1, "postponed": 0}},
        "by_hour": {"10": {"planned": 1, "done": 1}},
        "by_category": {"work": {"planned": 1, "done": 1}},
        "postponed_targets": [],
        "trend_vs_prev": None,
        "narrative": None,
        "is_demo": False,
        "data_label": "real",
        "unexpected_extra_field": 123,
    }
    with pytest.raises(Exception):
        InsightsResponse.model_validate(payload)


def test_generate_coaching_narrative_with_llm() -> None:
    from app.api.insights import generate_coaching_narrative
    from unittest.mock import MagicMock

    mock_llm = MagicMock()
    mock_llm.complete.return_value = "Great job finishing your study session! Keep up the habit on Thursday."

    metrics = {
        "period": "week",
        "planned": 3,
        "done": 2,
        "postponed": 1,
        "skipped": 0,
        "adherence_pct": 66.7,
    }
    plans = [{"id": "p1", "title": "Math study"}]
    outcomes = [{"id": "o1", "plan_id": "p1", "status": "done"}]

    narrative = generate_coaching_narrative(
        mock_llm,
        metrics=metrics,
        plans=plans,
        outcomes=outcomes,
        user_timezone="Europe/Istanbul",
    )
    assert narrative == "Great job finishing your study session! Keep up the habit on Thursday."
    assert mock_llm.complete.called


def test_generate_coaching_narrative_fallback_on_llm_error() -> None:
    from app.api.insights import generate_coaching_narrative
    from app.ai.llm import LLMUnavailableError
    from unittest.mock import MagicMock

    mock_llm = MagicMock()
    mock_llm.complete.side_effect = LLMUnavailableError("Nebius service unavailable")

    metrics = {
        "period": "week",
        "planned": 4,
        "done": 3,
        "postponed": 1,
        "skipped": 0,
        "adherence_pct": 75.0,
    }
    narrative = generate_coaching_narrative(
        mock_llm,
        metrics=metrics,
        plans=[{"id": "p1", "title": "Yoga"}],
        outcomes=[],
        user_timezone="Europe/Istanbul",
    )
    assert narrative is not None
    assert "75%" in narrative
    assert "3 of 4" in narrative


def test_generate_coaching_narrative_deterministic_variants() -> None:
    from app.api.insights import generate_coaching_narrative

    # Variant 1: No plans at all
    n_empty = generate_coaching_narrative(
        None,
        metrics={"period": "week", "planned": 0, "done": 0, "postponed": 0, "skipped": 0, "adherence_pct": None},
        plans=[],
        outcomes=[],
        user_timezone="Europe/Istanbul",
    )
    assert "Welcome to your Personal AI Coach" in n_empty

    # Variant 2: Plans created (e.g. via ESP32 voice) but not yet completed
    n_pending = generate_coaching_narrative(
        None,
        metrics={"period": "week", "planned": 2, "done": 0, "postponed": 0, "skipped": 0, "adherence_pct": None},
        plans=[{"id": "p1", "title": "Run"}, {"id": "p2", "title": "Read"}],
        outcomes=[],
        user_timezone="Europe/Istanbul",
    )
    assert "2 planned activities scheduled" in n_pending


def test_api_insights_returns_narrative_and_isolates_user(monkeypatch) -> None:
    from unittest.mock import MagicMock
    from app.ai.llm import get_llm_client

    settings = SimpleNamespace(
        token_hash_pepper=SecretStr(PEPPER),
        allowed_origins=[],
        supabase_url=None,
        supabase_service_key=None,
    )
    monkeypatch.setattr("app.api.plans.get_settings", lambda: settings)

    fake_store = FakeInsightsStore()
    user_a = AuthenticatedUser("user-narrative-a", "Europe/Istanbul", False, None)
    user_b = AuthenticatedUser("user-narrative-b", "Europe/Istanbul", False, None)
    fake_store.tokens[HASH_USER_A] = (user_a, None)
    fake_store.tokens[HASH_USER_B] = (user_b, None)

    fake_store.add_plan(user_id="user-narrative-a", title="User A Private Run", start=datetime(2026, 10, 14, 10, 0, tzinfo=TZ_ISTANBUL))

    mock_llm = MagicMock()
    mock_llm.complete.return_value = "Keep moving, User A!"
    app.dependency_overrides[get_plan_store] = lambda: fake_store
    app.dependency_overrides[get_system_time] = lambda: FIXED_NOW
    app.dependency_overrides[get_llm_client] = lambda: mock_llm

    try:
        client = TestClient(app)
        resp_a = client.get("/insights", headers={"Authorization": f"Bearer {TOKEN_USER_A}"})
        assert resp_a.status_code == 200
        assert resp_a.json()["narrative"] == "Keep moving, User A!"

        # User B should NOT see User A's narrative or plans
        mock_llm.complete.return_value = "Welcome User B!"
        resp_b = client.get("/insights", headers={"Authorization": f"Bearer {TOKEN_USER_B}"})
        assert resp_b.status_code == 200
        assert resp_b.json()["planned"] == 0
        assert "User A Private Run" not in str(resp_b.json())
    finally:
        app.dependency_overrides.clear()


def test_contextual_early_habit_signals_when_outcomes_under_three() -> None:
    from app.recommendations import build_contextual_recommendations

    plans = [
        {"id": "p-done", "title": "Morning Walk", "category": "sport", "planned_start": "2026-10-15T09:00:00+03:00", "duration_minutes": 25},
    ]
    outcomes = [
        {"id": "o-done", "plan_id": "p-done", "status": "done", "reported_at": "2026-10-15T09:30:00+03:00"},
    ]
    cards = build_contextual_recommendations(
        profile={},
        plans=plans,
        now=FIXED_NOW,
        timezone_name="Europe/Istanbul",
        outcomes=outcomes,
    )
    early_done = [c for c in cards if c["id"].startswith("context-early-done")]
    assert len(early_done) == 1
    assert "Morning Walk" in early_done[0]["title"]
    assert early_done[0]["label"] == "Early habit signal"
    assert early_done[0]["duration_minutes"] == 25

