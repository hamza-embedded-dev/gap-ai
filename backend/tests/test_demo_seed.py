from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

import app.db.demo_seed as demo_seed


def test_materialize_demo_profile_shifts_timestamps_and_remaps_ids() -> None:
    session_started_at = datetime(2026, 10, 19, 12, 0, tzinfo=ZoneInfo("Europe/Istanbul"))

    plans, outcomes = demo_seed.materialize_demo_profile(
        "demo-user-1", session_started_at=session_started_at
    )
    second_plans, second_outcomes = demo_seed.materialize_demo_profile(
        "demo-user-2", session_started_at=session_started_at
    )

    assert len(plans) == 22
    assert plans[0]["planned_start"] == "2026-09-21T07:30:00+03:00"
    assert all(plan["user_id"] == "demo-user-1" for plan in plans)
    assert all("id" in plan and "day_offset" not in plan for plan in plans)
    assert {plan["id"] for plan in plans}.isdisjoint({plan["id"] for plan in second_plans})
    assert outcomes and all(outcome["plan_id"] in {p["id"] for p in plans} for outcome in outcomes)
    assert all(outcome["plan_id"] in {p["id"] for p in second_plans} for outcome in second_outcomes)
    assert outcomes[0]["reported_at"] == "2026-09-21T08:20:00+03:00"


def test_materialize_demo_profile_supports_the_procrastinator_profile() -> None:
    plans, outcomes = demo_seed.materialize_demo_profile(
        "demo-user", profile_id="procrastinator",
        session_started_at=datetime(2026, 10, 19, 9, 0, tzinfo=ZoneInfo("UTC")),
    )

    assert len(plans) == 24
    assert outcomes
    assert all(plan["user_id"] == "demo-user" for plan in plans)


def test_materialize_demo_profile_rejects_unknown_profile() -> None:
    with pytest.raises(ValueError, match="metadata or profile"):
        demo_seed.materialize_demo_profile(
            "demo-user", profile_id="missing",
            session_started_at=datetime(2026, 10, 19, 9, 0, tzinfo=ZoneInfo("UTC")),
        )


def test_materialize_demo_profile_rejects_outcome_with_unknown_plan(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    document = json.loads(demo_seed._DATASET_PATH.read_text(encoding="utf-8"))
    document["profiles"]["regular"]["outcomes"][0]["plan_id"] = "missing-plan"
    dataset_path = tmp_path / "demo_plans.json"
    dataset_path.write_text(json.dumps(document), encoding="utf-8")
    monkeypatch.setattr(demo_seed, "_DATASET_PATH", dataset_path)

    with pytest.raises(ValueError, match="unknown plan"):
        demo_seed.materialize_demo_profile(
            "demo-user", session_started_at=datetime(2026, 10, 19, 9, 0, tzinfo=ZoneInfo("UTC"))
        )
