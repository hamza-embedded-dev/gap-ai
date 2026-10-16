from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.api.errors import APIError
from app.api.plans import canonical_request_hash
from app.api.upcoming import UpcomingResponse, get_system_time, get_upcoming
from app.db.plans import AuthenticatedUser, get_plan_store
from app.main import app

PEPPER = "p" * 32
TOKEN_USER_ONE = "token-user-one"
TOKEN_USER_TWO = "token-user-two"
HASH_USER_ONE = hashlib.sha256((TOKEN_USER_ONE + PEPPER).encode("utf-8")).hexdigest()
HASH_USER_TWO = hashlib.sha256((TOKEN_USER_TWO + PEPPER).encode("utf-8")).hexdigest()

TZ_ISTANBUL = ZoneInfo("Europe/Istanbul")
FIXED_NOW = datetime(2026, 10, 16, 12, 0, 0, tzinfo=TZ_ISTANBUL)


class FakePlanStore:
    def __init__(self) -> None:
        self.plans: dict[str, dict[str, object]] = {}
        self.plan_owners: dict[str, str] = {}
        self.tokens: dict[str, tuple[AuthenticatedUser, str | None]] = {}

    def get_user_for_token_hash(self, token_hash: str):
        return self.tokens.get(token_hash)

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
            "source": "text",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "latest_outcome": None,
        }
        self.plans[plan_id] = plan
        self.plan_owners[plan_id] = user_id
        return plan

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


@pytest.fixture
def fake_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "app.api.plans.get_settings",
        lambda: SimpleNamespace(
            token_hash_pepper=SecretStr(PEPPER),
            supabase_url=None,
            supabase_service_key=None,
        ),
    )
    store = FakePlanStore()
    user_one = AuthenticatedUser("user-one", "Europe/Istanbul", False, None)
    user_two = AuthenticatedUser("user-two", "Europe/Istanbul", False, None)

    store.tokens[HASH_USER_ONE] = (user_one, None)
    store.tokens[HASH_USER_TWO] = (user_two, None)

    app.dependency_overrides[get_plan_store] = lambda: store
    app.dependency_overrides[get_system_time] = lambda: FIXED_NOW
    yield store, user_one, user_two
    app.dependency_overrides.clear()


@pytest.fixture
def client(fake_env) -> TestClient:
    return TestClient(app)


def _auth(token: str = TOKEN_USER_ONE) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# --- Unit Tests on Route Function --------------------------------------------


def test_upcoming_empty_when_no_plans(fake_env) -> None:
    store, user, _ = fake_env
    response = get_upcoming(
        user=user,
        store=store,
        current_time=FIXED_NOW,
    )
    assert response == {"items": []}
    # Validate with Pydantic model
    validated = UpcomingResponse.model_validate(response)
    assert validated.items == []


def test_upcoming_default_24h_window_and_ordering(fake_env) -> None:
    store, user, _ = fake_env

    # 1. Past plan (2 hours ago) -> should NOT be included
    store.add_plan(user_id=user.id, title="Past Plan", start=FIXED_NOW - timedelta(hours=2))

    # 2. Plan right now -> should be included
    plan_now = store.add_plan(user_id=user.id, title="Now Plan", start=FIXED_NOW)

    # 3. Plan in 6 hours -> should be included
    plan_later = store.add_plan(user_id=user.id, title="Later Plan", start=FIXED_NOW + timedelta(hours=6))

    # 4. Plan in 2 hours -> should be included
    plan_soon = store.add_plan(user_id=user.id, title="Soon Plan", start=FIXED_NOW + timedelta(hours=2))

    # 5. Plan at exactly +24h boundary -> should be included
    plan_boundary = store.add_plan(
        user_id=user.id, title="Boundary Plan", start=FIXED_NOW + timedelta(hours=24)
    )

    # 6. Plan in 25 hours -> should NOT be included
    store.add_plan(user_id=user.id, title="Far Plan", start=FIXED_NOW + timedelta(hours=25))

    response = get_upcoming(user=user, store=store, current_time=FIXED_NOW)
    items = response["items"]

    assert len(items) == 4
    # Check ascending order: now, soon (+2h), later (+6h), boundary (+24h)
    assert [item["plan_id"] for item in items] == [
        plan_now["id"],
        plan_soon["id"],
        plan_later["id"],
        plan_boundary["id"],
    ]


def test_upcoming_k4_reminder_offset_15_minutes(fake_env) -> None:
    store, user, _ = fake_env
    # Plan starting at 18:00
    plan_start = datetime(2026, 10, 16, 18, 0, 0, tzinfo=TZ_ISTANBUL)
    plan = store.add_plan(user_id=user.id, title="Evening Run", start=plan_start)

    response = get_upcoming(user=user, store=store, current_time=FIXED_NOW)
    items = response["items"]

    assert len(items) == 1
    item = items[0]
    assert item["plan_id"] == plan["id"]
    assert item["title"] == "Evening Run"
    assert item["planned_start"] == plan_start

    # K-4: reminder_at = planned_start - 15 minutes
    expected_reminder = datetime(2026, 10, 16, 17, 45, 0, tzinfo=TZ_ISTANBUL)
    assert item["reminder_at"] == expected_reminder


def test_upcoming_reminder_midnight_transition(fake_env) -> None:
    store, user, _ = fake_env
    # Plan starting at 00:05 on next day (Oct 17)
    plan_start = datetime(2026, 10, 17, 0, 5, 0, tzinfo=TZ_ISTANBUL)
    plan = store.add_plan(user_id=user.id, title="Midnight Study", start=plan_start)

    response = get_upcoming(user=user, store=store, current_time=FIXED_NOW)
    items = response["items"]

    assert len(items) == 1
    item = items[0]
    # Reminder must be at 23:50 on previous day (Oct 16)
    expected_reminder = datetime(2026, 10, 16, 23, 50, 0, tzinfo=TZ_ISTANBUL)
    assert item["planned_start"] == plan_start
    assert item["reminder_at"] == expected_reminder


def test_upcoming_strictly_isolates_users(fake_env) -> None:
    store, user_one, user_two = fake_env
    plan_one = store.add_plan(
        user_id=user_one.id, title="User One Run", start=FIXED_NOW + timedelta(hours=3)
    )
    plan_two = store.add_plan(
        user_id=user_two.id, title="User Two Gym", start=FIXED_NOW + timedelta(hours=3)
    )

    items_one = get_upcoming(user=user_one, store=store, current_time=FIXED_NOW)["items"]
    items_two = get_upcoming(user=user_two, store=store, current_time=FIXED_NOW)["items"]

    assert len(items_one) == 1
    assert items_one[0]["plan_id"] == plan_one["id"]
    assert items_one[0]["title"] == "User One Run"

    assert len(items_two) == 1
    assert items_two[0]["plan_id"] == plan_two["id"]
    assert items_two[0]["title"] == "User Two Gym"


def test_upcoming_custom_since_and_to_filters(fake_env) -> None:
    store, user, _ = fake_env
    plan1 = store.add_plan(
        user_id=user.id, title="P1", start=datetime(2026, 10, 16, 14, 0, tzinfo=TZ_ISTANBUL)
    )
    plan2 = store.add_plan(
        user_id=user.id, title="P2", start=datetime(2026, 10, 16, 16, 0, tzinfo=TZ_ISTANBUL)
    )
    plan3 = store.add_plan(
        user_id=user.id, title="P3", start=datetime(2026, 10, 16, 18, 0, tzinfo=TZ_ISTANBUL)
    )

    # Filter between 15:00 and 17:00
    filter_since = datetime(2026, 10, 16, 15, 0, tzinfo=TZ_ISTANBUL)
    filter_to = datetime(2026, 10, 16, 17, 0, tzinfo=TZ_ISTANBUL)

    response = get_upcoming(
        user=user,
        store=store,
        since=filter_since,
        to=filter_to,
        current_time=FIXED_NOW,
    )
    items = response["items"]

    assert len(items) == 1
    assert items[0]["plan_id"] == plan2["id"]


def test_upcoming_reversed_time_range_returns_422(fake_env) -> None:
    store, user, _ = fake_env
    since = datetime(2026, 10, 16, 18, 0, tzinfo=TZ_ISTANBUL)
    to = datetime(2026, 10, 16, 12, 0, tzinfo=TZ_ISTANBUL)

    with pytest.raises(APIError) as exc_info:
        get_upcoming(
            user=user,
            store=store,
            since=since,
            to=to,
            current_time=FIXED_NOW,
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.error == "validation_error"


def test_upcoming_invalid_user_timezone_returns_422(fake_env) -> None:
    store, _, _ = fake_env
    invalid_tz_user = AuthenticatedUser("u-inv", "Invalid/Timezone_Name", False, None)

    with pytest.raises(APIError) as exc_info:
        get_upcoming(user=invalid_tz_user, store=store, current_time=FIXED_NOW)

    assert exc_info.value.status_code == 422
    assert exc_info.value.error == "validation_error"


def test_upcoming_raises_not_implemented_when_store_lacks_list_plans() -> None:
    class IncompleteStore:
        pass

    user = AuthenticatedUser("user-one", "Europe/Istanbul", False, None)
    with pytest.raises(NotImplementedError, match="does not support list_plans yet"):
        get_upcoming(user=user, store=IncompleteStore(), current_time=FIXED_NOW)  # type: ignore[arg-type]


# --- HTTP / TestClient Integration Tests -------------------------------------


def test_client_get_upcoming_without_auth_returns_401(client: TestClient) -> None:
    response = client.get("/me/upcoming")
    assert response.status_code == 401
    assert response.json()["error"] == "unauthorized"


def test_client_get_upcoming_with_invalid_token_returns_401(client: TestClient) -> None:
    response = client.get("/me/upcoming", headers={"Authorization": "Bearer bad-token"})
    assert response.status_code == 401
    assert response.json()["error"] == "unauthorized"


def test_client_get_upcoming_with_expired_token_returns_401(fake_env, client: TestClient) -> None:
    store, _, _ = fake_env
    expired_token = "expired-token"
    expired_hash = hashlib.sha256((expired_token + PEPPER).encode("utf-8")).hexdigest()
    user = AuthenticatedUser("u-exp", "Europe/Istanbul", False, None)
    # Expired 1 hour ago
    store.tokens[expired_hash] = (
        user,
        (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
    )

    response = client.get("/me/upcoming", headers={"Authorization": f"Bearer {expired_token}"})
    assert response.status_code == 401
    assert response.json()["error"] == "unauthorized"


def test_client_get_upcoming_returns_200_with_contract_json(fake_env, client: TestClient) -> None:
    store, user, _ = fake_env
    plan_start = FIXED_NOW + timedelta(hours=4)
    plan = store.add_plan(user_id=user.id, title="Yoga", start=plan_start)

    response = client.get("/me/upcoming", headers=_auth())
    assert response.status_code == 200

    data = response.json()
    assert "items" in data
    assert len(data["items"]) == 1

    item = data["items"][0]
    assert item["plan_id"] == plan["id"]
    assert item["title"] == "Yoga"
    assert "planned_start" in item
    assert "reminder_at" in item

    # Contract adherence: forbidden fields from /plans must NOT be present
    assert "category" not in item
    assert "latest_outcome" not in item
    assert "planned_end" not in item
    assert "source" not in item
    assert "created_at" not in item

    # Verify timestamp strings format
    assert item["planned_start"].startswith("2026-10-16T16:00:00")
    assert item["reminder_at"].startswith("2026-10-16T15:45:00")


def test_client_get_upcoming_with_query_params(fake_env, client: TestClient) -> None:
    store, user, _ = fake_env
    store.add_plan(user_id=user.id, title="Morning", start=FIXED_NOW + timedelta(hours=1))
    store.add_plan(user_id=user.id, title="Night", start=FIXED_NOW + timedelta(hours=10))

    since_str = (FIXED_NOW + timedelta(hours=5)).isoformat()
    to_str = (FIXED_NOW + timedelta(hours=12)).isoformat()

    response = client.get(
        "/me/upcoming",
        headers=_auth(),
        params={"since": since_str, "to": to_str},
    )
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["title"] == "Night"


def test_client_get_upcoming_reversed_dates_returns_422(client: TestClient) -> None:
    since_str = "2026-10-17T18:00:00+03:00"
    to_str = "2026-10-16T18:00:00+03:00"

    response = client.get(
        "/me/upcoming",
        headers=_auth(),
        params={"since": since_str, "to": to_str},
    )
    assert response.status_code == 422
    assert response.json()["error"] == "validation_error"


def test_client_get_upcoming_invalid_datetime_format_returns_422(client: TestClient) -> None:
    response = client.get(
        "/me/upcoming",
        headers=_auth(),
        params={"since": "not-a-valid-date"},
    )
    assert response.status_code == 422
    assert response.json()["error"] == "validation_error"
