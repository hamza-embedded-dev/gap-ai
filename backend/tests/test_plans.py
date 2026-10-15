from __future__ import annotations

import threading
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from uuid import uuid4

import pytest
import httpx
from pydantic import ValidationError

from app.api.errors import APIError
from app.api.plans import (
    PlanCreateRequest,
    PlanListResponse,
    canonical_request_hash,
    create_plan,
    list_plans,
)
from app.db.plans import AuthenticatedUser, SupabasePlanStore


def _valid_plan(**changes: object) -> dict[str, object]:
    plan: dict[str, object] = {
        "intent": "create_plan",
        "title": "Run",
        "category": "sport",
        "date": "2026-10-15",
        "time": "18:30",
        "duration_minutes": 60,
        "recurrence": None,
        "language": "en",
        "needs_weather_check": False,
        "clarification_question": None,
        "confidence": 0.95,
    }
    plan.update(changes)
    return plan


class FakePlanStore:
    def __init__(self) -> None:
        self.plans: dict[str, dict[str, object]] = {}
        self.plan_owners: dict[str, str] = {}
        self.requests: dict[tuple[str, str], dict[str, object]] = {}
        self._lock = threading.Lock()
        self.create_count = 0

    def get_user_for_token_hash(self, token_hash: str):
        raise AssertionError("Authentication is injected for these route unit tests.")

    def create_plan(self, plan: dict[str, object]) -> dict[str, object]:
        with self._lock:
            self.create_count += 1
            snapshot = self._snapshot(plan)
            self.plans[snapshot["id"]] = snapshot
            self.plan_owners[snapshot["id"]] = str(plan.get("user_id") or "")
            return snapshot

    def create_plan_idempotently(
        self,
        *,
        user_id: str,
        idempotency_key: str,
        request_hash: str,
        plan: dict[str, object],
    ):
        with self._lock:
            key = (user_id, idempotency_key)
            existing = self.requests.get(key)
            if existing is not None:
                return existing["response_snapshot"], existing["request_hash"] != request_hash
            self.create_count += 1
            snapshot = self._snapshot(plan)
            self.plans[snapshot["id"]] = snapshot
            self.plan_owners[snapshot["id"]] = user_id
            self.requests[key] = {
                "request_hash": request_hash,
                "response_snapshot": snapshot,
                "plan_id": snapshot["id"],
            }
            return snapshot, False

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
        with self._lock:
            matching: list[dict[str, object]] = []
            for plan_id, snapshot in self.plans.items():
                if self.plan_owners.get(plan_id) != user_id:
                    continue
                start_dt = datetime.fromisoformat(
                    str(snapshot["planned_start"]).replace("Z", "+00:00")
                )
                if effective_from is not None:
                    norm_from = effective_from if effective_from.tzinfo else effective_from.replace(tzinfo=start_dt.tzinfo)
                    if start_dt < norm_from:
                        continue
                if effective_to is not None:
                    norm_to = effective_to if effective_to.tzinfo else effective_to.replace(tzinfo=start_dt.tzinfo)
                    if start_dt > norm_to:
                        continue
                matching.append(snapshot)
            matching.sort(
                key=lambda p: datetime.fromisoformat(str(p["planned_start"]).replace("Z", "+00:00"))
            )
            return matching

    def delete_plan(self, user_id: str, idempotency_key: str) -> None:
        record = self.requests[(user_id, idempotency_key)]
        self.plans.pop(record["plan_id"], None)
        self.plan_owners.pop(record["plan_id"], None)
        record["plan_id"] = None

    def _snapshot(self, plan: dict[str, object]) -> dict[str, object]:
        return {
            "id": str(uuid4()),
            "title": plan["title"],
            "category": plan["category"],
            "planned_start": plan["planned_start"],
            "planned_end": plan["planned_end"],
            "recurrence_rule": plan["recurrence_rule"],
            "source": plan["source"],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "latest_outcome": None,
        }


@pytest.fixture
def store_and_users() -> tuple[FakePlanStore, AuthenticatedUser, AuthenticatedUser]:
    return (
        FakePlanStore(),
        AuthenticatedUser("user-one", "Europe/Istanbul", False, None),
        AuthenticatedUser("user-two", "Europe/Istanbul", False, None),
    )


def _call(
    store: FakePlanStore,
    user: AuthenticatedUser,
    payload: dict[str, object],
    key: str | None = None,
) -> dict[str, object]:
    return create_plan(
        PlanCreateRequest.model_validate(payload),
        user,
        store,
        key,
    )


def _call_list(
    store: FakePlanStore,
    user: AuthenticatedUser,
    from_: datetime | None = None,
    to: datetime | None = None,
) -> dict[str, object]:
    return list_plans(
        user=user,
        store=store,
        from_=from_,
        to=to,
    )


def test_first_idempotent_request_creates_plan_and_stores_snapshot(store_and_users) -> None:
    store, user, _ = store_and_users
    response = _call(store, user, {"parsed_plan": _valid_plan(), "source": "text"}, "once")

    assert response["latest_outcome"] is None
    record = store.requests[(user.id, "once")]
    assert record["response_snapshot"] == response
    assert store.create_count == 1


def test_request_hash_uses_canonical_utf8_json_and_sha256() -> None:
    request = PlanCreateRequest.model_validate(
        {"parsed_plan": _valid_plan(), "source": "text"}
    )
    canonical = json.dumps(
        request.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")

    assert canonical_request_hash(request) == hashlib.sha256(canonical).hexdigest()


def test_unknown_request_field_is_rejected_before_idempotency_hashing() -> None:
    payload = {"parsed_plan": _valid_plan(), "source": "text", "unexpected": "value"}

    with pytest.raises(ValidationError):
        PlanCreateRequest.model_validate(payload)


def test_same_key_and_payload_replays_stored_response(store_and_users) -> None:
    store, user, _ = store_and_users
    payload = {"parsed_plan": _valid_plan(), "source": "text"}

    first = _call(store, user, payload, "once")
    second = _call(store, user, payload, "once")

    assert second == first
    assert store.create_count == 1


def test_changed_payload_with_existing_key_returns_contract_422(store_and_users) -> None:
    store, user, _ = store_and_users
    _call(store, user, {"parsed_plan": _valid_plan(), "source": "text"}, "once")

    with pytest.raises(APIError) as error:
        _call(store, user, {"parsed_plan": _valid_plan(title="Study"), "source": "text"}, "once")

    assert error.value.status_code == 422
    assert error.value.error == "validation_error"
    assert store.create_count == 1


def test_impossible_calendar_date_returns_contract_422_without_creating_plan(store_and_users) -> None:
    store, user, _ = store_and_users
    payload = {"parsed_plan": _valid_plan(date="2026-02-31"), "source": "text"}

    with pytest.raises(APIError) as error:
        _call(store, user, payload, "invalid-date")

    assert error.value.status_code == 422
    assert error.value.error == "validation_error"
    assert store.create_count == 0


def test_empty_title_allowed_by_contract_and_database_schema(store_and_users) -> None:
    store, user, _ = store_and_users

    response = _call(store, user, {"parsed_plan": _valid_plan(title=""), "source": "text"})

    assert response["title"] == ""


def test_same_key_is_independent_between_users(store_and_users) -> None:
    store, user_one, user_two = store_and_users
    payload = {"parsed_plan": _valid_plan(), "source": "text"}

    first = _call(store, user_one, payload, "shared-key")
    second = _call(store, user_two, payload, "shared-key")

    assert first["id"] != second["id"]
    assert store.create_count == 2


def test_concurrent_same_key_requests_create_only_one_plan(store_and_users) -> None:
    store, user, _ = store_and_users
    payload = {"parsed_plan": _valid_plan(), "source": "text"}

    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(lambda _: _call(store, user, payload, "racing-key"), range(8)))

    assert len({response["id"] for response in responses}) == 1
    assert store.create_count == 1


def test_supabase_rpc_retries_transaction_conflict_then_uses_snapshot() -> None:
    calls = 0
    snapshot = {"id": "original-plan"}

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(409, json={"code": "40001"}, request=request)
        return httpx.Response(
            200,
            json={"conflict": False, "response_snapshot": snapshot},
            request=request,
        )

    store = SupabasePlanStore("https://example.invalid", "test-service-key")
    store._client.close()
    store._client = httpx.Client(transport=httpx.MockTransport(respond))
    try:
        result, conflict = store.create_plan_idempotently(
            user_id="user-one",
            idempotency_key="same-key",
            request_hash="request-hash",
            plan={
                "title": "Run",
                "category": "sport",
                "planned_start": "2026-10-15T18:30:00+03:00",
                "planned_end": "2026-10-15T19:30:00+03:00",
                "recurrence_rule": None,
                "source": "text",
            },
        )
    finally:
        store._client.close()

    assert calls == 2
    assert result == snapshot
    assert conflict is False


def test_replay_after_plan_deletion_keeps_original_snapshot(store_and_users) -> None:
    store, user, _ = store_and_users
    payload = {"parsed_plan": _valid_plan(), "source": "text"}
    first = _call(store, user, payload, "deleted-plan")
    store.delete_plan(user.id, "deleted-plan")

    replay = _call(store, user, payload, "deleted-plan")

    assert replay == first
    assert store.requests[(user.id, "deleted-plan")]["plan_id"] is None
    assert store.create_count == 1


def test_missing_idempotency_key_preserves_regular_create_behavior(store_and_users) -> None:
    store, user, _ = store_and_users
    payload = {"parsed_plan": _valid_plan(), "source": "text"}

    first = _call(store, user, payload)
    second = _call(store, user, payload)

    assert first["id"] != second["id"]
    assert store.requests == {}
    assert store.create_count == 2


@pytest.mark.parametrize("intent", ["clarify", "unsupported"])
def test_non_create_intents_are_rejected(store_and_users, intent: str) -> None:
    store, user, _ = store_and_users
    parsed = _valid_plan(
        intent=intent,
        title=None,
        category=None,
        date=None,
        time=None,
        duration_minutes=None,
        recurrence=None,
        clarification_question="Which day?" if intent == "clarify" else None,
    )

    with pytest.raises(APIError) as error:
        _call(store, user, {"parsed_plan": parsed, "source": "text"}, "not-created")

    assert error.value.status_code == 422
    assert error.value.error == "validation_error"
    assert store.create_count == 0


def test_list_plans_returns_empty_when_no_plans(store_and_users) -> None:
    store, user, _ = store_and_users
    result = _call_list(store, user)

    assert result == {"items": []}


def test_list_plans_strictly_isolates_users(store_and_users) -> None:
    store, user_one, user_two = store_and_users
    plan_one = _call(store, user_one, {"parsed_plan": _valid_plan(title="User One Plan"), "source": "text"})
    plan_two = _call(store, user_two, {"parsed_plan": _valid_plan(title="User Two Plan"), "source": "text"})

    items_one = _call_list(store, user_one)["items"]
    items_two = _call_list(store, user_two)["items"]

    assert len(items_one) == 1
    assert items_one[0]["id"] == plan_one["id"]
    assert items_one[0]["title"] == "User One Plan"

    assert len(items_two) == 1
    assert items_two[0]["id"] == plan_two["id"]
    assert items_two[0]["title"] == "User Two Plan"


def test_list_plans_sorted_by_planned_start_ascending(store_and_users) -> None:
    store, user, _ = store_and_users
    evening = _call(store, user, {"parsed_plan": _valid_plan(title="Evening Run", time="19:00"), "source": "text"})
    morning = _call(store, user, {"parsed_plan": _valid_plan(title="Morning Walk", time="07:30"), "source": "text"})
    afternoon = _call(store, user, {"parsed_plan": _valid_plan(title="Lunch Gym", time="12:00"), "source": "text"})

    items = _call_list(store, user)["items"]

    assert [p["id"] for p in items] == [morning["id"], afternoon["id"], evening["id"]]


def test_list_plans_includes_latest_outcome_field(store_and_users) -> None:
    store, user, _ = store_and_users
    _call(store, user, {"parsed_plan": _valid_plan(), "source": "text"})

    items = _call_list(store, user)["items"]

    assert len(items) == 1
    assert "latest_outcome" in items[0]
    assert items[0]["latest_outcome"] is None


def test_list_plans_filters_by_from_inclusive(store_and_users) -> None:
    store, user, _ = store_and_users
    day1 = _call(store, user, {"parsed_plan": _valid_plan(title="Day 1", date="2026-10-14", time="10:00"), "source": "text"})
    day2 = _call(store, user, {"parsed_plan": _valid_plan(title="Day 2", date="2026-10-15", time="10:00"), "source": "text"})
    day3 = _call(store, user, {"parsed_plan": _valid_plan(title="Day 3", date="2026-10-16", time="10:00"), "source": "text"})

    filter_from = datetime.fromisoformat("2026-10-15T10:00:00+03:00")
    items = _call_list(store, user, from_=filter_from)["items"]

    assert [p["id"] for p in items] == [day2["id"], day3["id"]]


def test_list_plans_filters_by_to_inclusive(store_and_users) -> None:
    store, user, _ = store_and_users
    day1 = _call(store, user, {"parsed_plan": _valid_plan(title="Day 1", date="2026-10-14", time="10:00"), "source": "text"})
    day2 = _call(store, user, {"parsed_plan": _valid_plan(title="Day 2", date="2026-10-15", time="10:00"), "source": "text"})
    day3 = _call(store, user, {"parsed_plan": _valid_plan(title="Day 3", date="2026-10-16", time="10:00"), "source": "text"})

    filter_to = datetime.fromisoformat("2026-10-15T10:00:00+03:00")
    items = _call_list(store, user, to=filter_to)["items"]

    assert [p["id"] for p in items] == [day1["id"], day2["id"]]


def test_list_plans_filters_by_from_and_to_range_inclusive(store_and_users) -> None:
    store, user, _ = store_and_users
    day1 = _call(store, user, {"parsed_plan": _valid_plan(title="Day 1", date="2026-10-14", time="10:00"), "source": "text"})
    day2 = _call(store, user, {"parsed_plan": _valid_plan(title="Day 2", date="2026-10-15", time="10:00"), "source": "text"})
    day3 = _call(store, user, {"parsed_plan": _valid_plan(title="Day 3", date="2026-10-16", time="10:00"), "source": "text"})

    f_from = datetime.fromisoformat("2026-10-15T00:00:00+03:00")
    f_to = datetime.fromisoformat("2026-10-15T23:59:59+03:00")
    items = _call_list(store, user, from_=f_from, to=f_to)["items"]

    assert [p["id"] for p in items] == [day2["id"]]


def test_list_plans_raises_not_implemented_if_store_lacks_method() -> None:
    class IncompleteStore:
        pass

    user = AuthenticatedUser("user-one", "Europe/Istanbul", False, None)
    with pytest.raises(NotImplementedError, match="does not support list_plans"):
        list_plans(user, IncompleteStore())  # type: ignore[arg-type]
