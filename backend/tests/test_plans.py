from __future__ import annotations

import threading
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
import httpx
from pydantic import ValidationError

from app.api.errors import APIError
from app.api.plans import (
    PlanCreateRequest,
    PlanListResponse,
    PlanUpdateRequest,
    canonical_request_hash,
    create_plan,
    delete_plan,
    list_plans,
    update_plan,
)
import app.db.plans as db_plans
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

    def update_plan(self, *, user_id: str, plan_id: str, changes: dict[str, object]):
        if self.plan_owners.get(plan_id) != user_id:
            return None
        self.plans[plan_id].update(changes)
        return self.plans[plan_id]

    def delete_plan(self, *, user_id: str, plan_id: str) -> bool:
        if self.plan_owners.get(plan_id) != user_id:
            return False
        self.plans.pop(plan_id, None)
        self.plan_owners.pop(plan_id, None)
        for record in self.requests.values():
            if record["plan_id"] == plan_id:
                record["plan_id"] = None
        return True

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


def _valid_update(**changes: object) -> dict[str, object]:
    values: dict[str, object] = {
        "title": "Updated Run",
        "category": "sport",
        "planned_start": "2026-10-18T18:30:00+03:00",
        "planned_end": "2026-10-18T19:30:00+03:00",
    }
    values.update(changes)
    return values


def test_update_plan_persists_supported_fields_for_the_authenticated_owner(store_and_users) -> None:
    store, user, _ = store_and_users
    original = _call(store, user, {"parsed_plan": _valid_plan(), "source": "text"})

    updated = update_plan(
        str(original["id"]), PlanUpdateRequest.model_validate(_valid_update()), user, store
    )

    assert updated["title"] == "Updated Run"
    assert updated["category"] == "sport"
    assert updated["planned_start"] == "2026-10-18T18:30:00+03:00"
    assert updated["planned_end"] == "2026-10-18T19:30:00+03:00"
    assert updated["source"] == "text"


def test_update_plan_does_not_allow_another_user_to_change_it(store_and_users) -> None:
    store, owner, other_user = store_and_users
    original = _call(store, owner, {"parsed_plan": _valid_plan(), "source": "text"})

    with pytest.raises(APIError) as error:
        update_plan(
            str(original["id"]), PlanUpdateRequest.model_validate(_valid_update()), other_user, store
        )

    assert error.value.status_code == 404
    assert store.plans[str(original["id"])]["title"] == original["title"]


def test_update_plan_rejects_invalid_or_missing_plan_ids(store_and_users) -> None:
    store, user, _ = store_and_users

    with pytest.raises(APIError) as error:
        update_plan("not-a-uuid", PlanUpdateRequest.model_validate(_valid_update()), user, store)

    assert error.value.status_code == 404
    with pytest.raises(APIError) as error:
        update_plan(str(uuid4()), PlanUpdateRequest.model_validate(_valid_update()), user, store)
    assert error.value.status_code == 404


@pytest.mark.parametrize(
    "changes",
    [
        {"title": "  "},
        {"category": "invalid"},
        {"planned_start": "2026-10-18T18:30:00"},
        {"planned_end": "2026-10-18T18:00:00+03:00"},
        {"description": "not a stored plan field"},
    ],
)
def test_plan_update_validation_rejects_unsupported_or_invalid_fields(changes) -> None:
    with pytest.raises(ValidationError):
        PlanUpdateRequest.model_validate(_valid_update(**changes))


def test_delete_plan_removes_only_owned_plan_and_preserves_idempotency_record(store_and_users) -> None:
    store, owner, other_user = store_and_users
    original = _call(
        store, owner, {"parsed_plan": _valid_plan(), "source": "text"}, "keep-replay"
    )
    unrelated = _call(store, other_user, {"parsed_plan": _valid_plan(), "source": "text"})

    with pytest.raises(APIError) as forbidden:
        delete_plan(str(original["id"]), other_user, store)
    assert forbidden.value.status_code == 404
    assert str(original["id"]) in store.plans

    response = delete_plan(str(original["id"]), owner, store)
    assert response.status_code == 204
    assert str(original["id"]) not in store.plans
    assert str(unrelated["id"]) in store.plans
    assert store.requests[(owner.id, "keep-replay")]["plan_id"] is None


def test_delete_plan_returns_not_found_for_invalid_or_missing_plan(store_and_users) -> None:
    store, user, _ = store_and_users
    for plan_id in ("not-a-uuid", str(uuid4())):
        with pytest.raises(APIError) as error:
            delete_plan(plan_id, user, store)
        assert error.value.status_code == 404


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


class PlanMutationAPI:
    def __init__(self, row: dict[str, object]) -> None:
        self.rows = {str(row["id"]): row}
        self.requests: list[httpx.Request] = []
        self.fail = False

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        assert request.url.path == "/rest/v1/plans"
        if self.fail:
            return httpx.Response(503, json={"message": "database unavailable"}, request=request)
        plan_id = request.url.params["id"].removeprefix("eq.")
        owner_id = request.url.params["user_id"].removeprefix("eq.")
        row = self.rows.get(plan_id)
        if row is None or row["user_id"] != owner_id:
            return httpx.Response(200, json=[], request=request)
        if request.method == "PATCH":
            row.update(json.loads(request.content))
            return httpx.Response(200, json=[row], request=request)
        if request.method == "DELETE":
            del self.rows[plan_id]
            return httpx.Response(200, json=[{"id": plan_id}], request=request)
        raise AssertionError(f"Unexpected method {request.method}")


def _plan_mutation_store(api: PlanMutationAPI) -> SupabasePlanStore:
    store = SupabasePlanStore("https://example.invalid", "test-service-key")
    store._client.close()
    store._client = httpx.Client(
        base_url="https://example.invalid", transport=httpx.MockTransport(api)
    )
    return store


def _stored_plan_row() -> dict[str, object]:
    return {
        "id": PLAN_ID,
        "user_id": "user-one",
        "title": "Morning Run",
        "category": "sport",
        "planned_start": "2026-10-18T15:30:00+00:00",
        "planned_end": "2026-10-18T16:30:00+00:00",
        "recurrence_rule": None,
        "source": "text",
        "created_at": "2026-10-10T10:00:00+00:00",
        "outcomes": [{
            "id": str(uuid4()),
            "status": "done",
            "actual_start": None,
            "postponed_to": None,
            "note": None,
            "reported_via": "web",
            "reported_at": "2026-10-18T16:00:00+00:00",
        }],
    }


def test_supabase_update_and_delete_filter_by_plan_and_authenticated_owner() -> None:
    api = PlanMutationAPI(_stored_plan_row())
    store = _plan_mutation_store(api)
    try:
        updated = store.update_plan(
            user_id="user-one",
            plan_id=PLAN_ID,
            changes={"title": "Lunch Run", "category": "sport"},
        )
        assert updated is not None
        assert updated["title"] == "Lunch Run"
        assert updated["latest_outcome"]["status"] == "done"
        assert api.requests[0].method == "PATCH"
        assert api.requests[0].url.params["id"] == f"eq.{PLAN_ID}"
        assert api.requests[0].url.params["user_id"] == "eq.user-one"

        assert store.delete_plan(user_id="user-two", plan_id=PLAN_ID) is False
        assert PLAN_ID in api.rows
        delete_request = api.requests[-1]
        assert delete_request.method == "DELETE"
        assert delete_request.url.params["id"] == f"eq.{PLAN_ID}"
        assert delete_request.url.params["user_id"] == "eq.user-two"

        assert store.delete_plan(user_id="user-one", plan_id=PLAN_ID) is True
        assert PLAN_ID not in api.rows
        assert api.requests[-1].headers["Prefer"] == "return=representation"
        assert store.delete_plan(user_id="user-one", plan_id=PLAN_ID) is False
    finally:
        store._client.close()


def test_supabase_delete_does_not_report_success_when_database_errors() -> None:
    api = PlanMutationAPI(_stored_plan_row())
    api.fail = True
    store = _plan_mutation_store(api)
    try:
        with pytest.raises(httpx.HTTPStatusError):
            store.delete_plan(user_id="user-one", plan_id=PLAN_ID)
    finally:
        store._client.close()


def test_replay_after_plan_deletion_keeps_original_snapshot(store_and_users) -> None:
    store, user, _ = store_and_users
    payload = {"parsed_plan": _valid_plan(), "source": "text"}
    first = _call(store, user, payload, "deleted-plan")
    store.delete_plan(user_id=user.id, plan_id=str(first["id"]))

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


# --- Suggestion storage (B3-7) ----------------------------------------------

PLAN_ID = "7b0d1c52-3f7e-4a57-9c0c-2b8f7f5e9a10"
SAVED_SUGGESTION = {
    "plan_id": PLAN_ID,
    "reason": "weather",
    "message": "Rain expected. Move your run to Thursday 19:00?",
    "proposed_start": "2026-10-08T16:00:00+00:00",
    "proposed_end": "2026-10-08T17:00:00+00:00",
    "evidence": {"forecast": "rain", "adherence_pct": 66.7},
}


class SuggestionAPI:
    """Fake PostgREST /suggestions endpoint that records every request."""

    def __init__(self, stored: list[dict[str, object]] | None = None) -> None:
        self.stored = stored or []
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        assert request.url.path == "/rest/v1/suggestions"
        if request.method == "GET":
            user = request.url.params["user_id"].removeprefix("eq.")
            plan = request.url.params["plan_id"].removeprefix("eq.")
            rows = [s for s in self.stored if s["user_id"] == user and s["plan_id"] == plan]
            return httpx.Response(200, json=[_public(s) for s in rows[:1]], request=request)
        row = json.loads(request.content)
        if any(s["plan_id"] == row["plan_id"] for s in self.stored):
            return httpx.Response(201, json=[], request=request)  # ignore-duplicates
        self.stored.append(row)
        return httpx.Response(201, json=[_public(row)], request=request)


def _public(row: dict[str, object]) -> dict[str, object]:
    return {key: row[key] for key in SAVED_SUGGESTION}


def _suggestion_store(api: SuggestionAPI) -> SupabasePlanStore:
    store = SupabasePlanStore("https://example.invalid", "test-service-key")
    store._client.close()
    store._client = httpx.Client(
        base_url="https://example.invalid", transport=httpx.MockTransport(api)
    )
    return store


def _new_suggestion(**changes: object) -> dict[str, object]:
    data = {key: value for key, value in SAVED_SUGGESTION.items() if key != "plan_id"}
    data.update(changes)
    return data


def test_get_suggestion_filters_by_user_and_plan() -> None:
    api = SuggestionAPI([{**SAVED_SUGGESTION, "user_id": "user-one"}])
    store = _suggestion_store(api)

    assert store.get_suggestion("user-one", PLAN_ID) == SAVED_SUGGESTION
    params = api.requests[0].url.params
    assert params["user_id"] == "eq.user-one"
    assert params["plan_id"] == f"eq.{PLAN_ID}"
    assert params["select"] == "plan_id,reason,message,proposed_start,proposed_end,evidence"


def test_get_suggestion_returns_none_when_nothing_saved() -> None:
    store = _suggestion_store(SuggestionAPI())

    assert store.get_suggestion("user-one", PLAN_ID) is None


def test_get_suggestion_does_not_leak_another_users_suggestion() -> None:
    store = _suggestion_store(SuggestionAPI([{**SAVED_SUGGESTION, "user_id": "user-two"}]))

    assert store.get_suggestion("user-one", PLAN_ID) is None


def test_save_suggestion_then_read_returns_same_suggestion() -> None:
    api = SuggestionAPI()
    store = _suggestion_store(api)

    saved = store.save_suggestion("user-one", PLAN_ID, _new_suggestion())

    assert saved == SAVED_SUGGESTION
    assert store.get_suggestion("user-one", PLAN_ID) == saved
    post = api.requests[0]
    assert post.method == "POST"
    assert post.url.params["on_conflict"] == "plan_id"
    assert "resolution=ignore-duplicates" in post.headers["Prefer"]
    assert "return=representation" in post.headers["Prefer"]


def test_save_suggestion_uses_owner_from_arguments_only() -> None:
    api = SuggestionAPI()
    store = _suggestion_store(api)

    store.save_suggestion("user-one", PLAN_ID, _new_suggestion(user_id="user-two"))

    body = json.loads(api.requests[0].content)
    assert body["user_id"] == "user-one"
    assert body["plan_id"] == PLAN_ID


def test_save_suggestion_returns_first_saved_suggestion_on_conflict() -> None:
    api = SuggestionAPI([{**SAVED_SUGGESTION, "user_id": "user-one"}])
    store = _suggestion_store(api)

    result = store.save_suggestion(
        "user-one", PLAN_ID, _new_suggestion(reason="pattern", message="Try earlier.")
    )

    assert result == SAVED_SUGGESTION
    assert [r.method for r in api.requests] == ["POST", "GET"]
    assert len(api.stored) == 1


def test_save_suggestion_serializes_datetimes_with_offset() -> None:
    api = SuggestionAPI()
    store = _suggestion_store(api)
    start = datetime(2026, 10, 8, 19, 0, tzinfo=ZoneInfo("Europe/Istanbul"))

    store.save_suggestion(
        "user-one",
        PLAN_ID,
        _new_suggestion(proposed_start=start, proposed_end=start + timedelta(hours=1)),
    )

    body = json.loads(api.requests[0].content)
    assert body["proposed_start"] == "2026-10-08T19:00:00+03:00"
    assert body["proposed_end"] == "2026-10-08T20:00:00+03:00"


def test_save_suggestion_defaults_missing_evidence_to_empty_object() -> None:
    api = SuggestionAPI()
    store = _suggestion_store(api)
    data = _new_suggestion()
    del data["evidence"]

    store.save_suggestion("user-one", PLAN_ID, data)

    assert json.loads(api.requests[0].content)["evidence"] == {}


@pytest.mark.parametrize(
    "changes",
    [
        {"plan_id": "another-plan"},
        {"proposed_start": datetime(2026, 10, 8, 19, 0)},
    ],
    ids=["mismatched-plan-id", "naive-datetime"],
)
def test_save_suggestion_rejects_invalid_data_without_request(changes) -> None:
    api = SuggestionAPI()
    store = _suggestion_store(api)

    with pytest.raises(ValueError):
        store.save_suggestion("user-one", PLAN_ID, _new_suggestion(**changes))

    assert api.requests == []


def test_lazy_store_delegates_suggestion_methods(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, tuple[object, ...]]] = []

    class Recorder:
        def get_suggestion(self, *args):
            calls.append(("get", args))
            return None

        def save_suggestion(self, *args):
            calls.append(("save", args))
            return SAVED_SUGGESTION

    monkeypatch.setattr(db_plans, "_build_plan_store", lambda: Recorder())
    lazy = db_plans.LazyPlanStore()

    assert lazy.get_suggestion("user-one", PLAN_ID) is None
    assert lazy.save_suggestion("user-one", PLAN_ID, {"reason": "weather"}) == SAVED_SUGGESTION
    assert calls == [
        ("get", ("user-one", PLAN_ID)),
        ("save", ("user-one", PLAN_ID, {"reason": "weather"})),
    ]
