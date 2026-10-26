from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError

from app.db.plans import AuthenticatedUser, SupabasePlanStore, get_plan_store
from app.api.me import (
    PersonalizationPatch,
    delete_profile_field,
    get_personalization,
    patch_personalization,
    reset_personalization,
)
from app.main import app

PEPPER = "p" * 32
TOKEN_ONE = "profile-token-one"
TOKEN_TWO = "profile-token-two"


def _hash(token: str) -> str:
    return hashlib.sha256((token + PEPPER).encode("utf-8")).hexdigest()


class ProfileStore:
    def __init__(self) -> None:
        self.tokens = {
            _hash(TOKEN_ONE): (AuthenticatedUser("user-one", "Europe/Istanbul", False, None, "Ada"), None),
            _hash(TOKEN_TWO): (AuthenticatedUser("user-two", "Europe/Berlin", False, None, "Lin"), None),
        }
        self.profiles = {
            "user-one": {"id": "user-one", "display_name": "Ada", "timezone": "Europe/Istanbul", "is_demo": False},
            "user-two": {"id": "user-two", "display_name": "Lin", "timezone": "Europe/Berlin", "is_demo": False},
        }
        self.updates: list[tuple[str, dict[str, object]]] = []
        self.personalization = {"user-one": {"user_id": "user-one", "interests": ["running"]}, "user-two": {"user_id": "user-two", "interests": ["music"]}}
        self.keep_data = {"plans": ["plan-a"], "outcomes": ["outcome-a"], "suggestions": ["suggestion-a"], "feedback": ["feedback-a"]}

    def get_user_for_token_hash(self, token_hash: str):
        return self.tokens.get(token_hash)

    def update_profile(self, *, user_id: str, changes: dict[str, object]):
        self.updates.append((user_id, changes))
        profile = self.profiles.get(user_id)
        if profile is None:
            return None
        profile.update(changes)
        return dict(profile)

    def get_personalization(self, *, user_id: str):
        return dict(self.personalization.get(user_id, {"user_id": user_id}))

    def update_personalization(self, *, user_id: str, changes: dict[str, object]):
        profile = self.personalization.setdefault(user_id, {"user_id": user_id})
        profile.update(changes)
        return dict(profile)

    def reset_personalization(self, *, user_id: str):
        self.personalization.pop(user_id, None)
        return True


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> ProfileStore:
    monkeypatch.setattr(
        "app.api.plans.get_settings",
        lambda: SimpleNamespace(token_hash_pepper=SecretStr(PEPPER)),
    )
    fake = ProfileStore()
    app.dependency_overrides[get_plan_store] = lambda: fake
    yield fake
    app.dependency_overrides.clear()


@pytest.fixture
def client(store: ProfileStore) -> TestClient:
    return TestClient(app)


def _auth(token: str = TOKEN_ONE) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_get_me_returns_authenticated_users_profile(client: TestClient) -> None:
    response = client.get("/me", headers=_auth())

    assert response.status_code == 200
    assert response.json() == {
        "id": "user-one",
        "display_name": "Ada",
        "timezone": "Europe/Istanbul",
        "is_demo": False,
    }


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer bad-token"}])
def test_get_me_requires_authentication(client: TestClient, headers: dict[str, str]) -> None:
    response = client.get("/me", headers=headers)

    assert response.status_code == 401
    assert response.json()["error"] == "unauthorized"


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer bad-token"}])
def test_patch_me_requires_authentication(
    client: TestClient, store: ProfileStore, headers: dict[str, str]
) -> None:
    response = client.patch("/me", headers=headers, json={"display_name": "Changed"})

    assert response.status_code == 401
    assert response.json()["error"] == "unauthorized"
    assert store.updates == []


def test_patch_me_updates_only_fields_supplied(client: TestClient, store: ProfileStore) -> None:
    response = client.patch("/me", headers=_auth(), json={"display_name": "Ada Lovelace"})

    assert response.status_code == 200
    assert response.json()["display_name"] == "Ada Lovelace"
    assert response.json()["timezone"] == "Europe/Istanbul"
    assert store.updates == [("user-one", {"display_name": "Ada Lovelace"})]


def test_patch_me_accepts_valid_iana_timezone(client: TestClient, store: ProfileStore) -> None:
    response = client.patch("/me", headers=_auth(), json={"timezone": "America/New_York"})

    assert response.status_code == 200
    assert response.json()["timezone"] == "America/New_York"
    assert store.updates == [("user-one", {"timezone": "America/New_York"})]


@pytest.mark.parametrize("timezone_name", ["Mars/Olympus", "", None])
def test_patch_me_rejects_invalid_or_null_timezone(
    client: TestClient, store: ProfileStore, timezone_name: str | None
) -> None:
    response = client.patch("/me", headers=_auth(), json={"timezone": timezone_name})

    assert response.status_code == 422
    assert response.json()["error"] == "validation_error"
    assert store.updates == []


def test_patch_me_rejects_unknown_fields(client: TestClient, store: ProfileStore) -> None:
    response = client.patch("/me", headers=_auth(), json={"id": "user-two"})

    assert response.status_code == 422
    assert store.updates == []


def test_patch_me_cannot_modify_another_users_profile(
    client: TestClient, store: ProfileStore
) -> None:
    response = client.patch(
        "/me", headers=_auth(TOKEN_TWO), json={"display_name": "Lin Updated"}
    )

    assert response.status_code == 200
    assert response.json()["id"] == "user-two"
    assert store.profiles["user-one"]["display_name"] == "Ada"
    assert store.profiles["user-two"]["display_name"] == "Lin Updated"
    assert store.updates == [("user-two", {"display_name": "Lin Updated"})]


def test_supabase_profile_update_filters_by_authenticated_user_id() -> None:
    captured: list[httpx.Request] = []
    returned = {
        "id": "user-one",
        "display_name": "Ada Lovelace",
        "timezone": "Europe/Istanbul",
        "is_demo": False,
    }

    def handle(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json=[returned], request=request)

    store = SupabasePlanStore("https://example.invalid", "service-key")
    headers = dict(store._client.headers)
    store._client.close()
    store._client = httpx.Client(transport=httpx.MockTransport(handle), headers=headers)
    try:
        result = store.update_profile(
            user_id="user-one", changes={"display_name": "Ada Lovelace"}
        )
    finally:
        store._client.close()

    assert result == returned
    request = captured[0]
    assert request.method == "PATCH"
    assert request.url.params["id"] == "eq.user-one"
    assert request.headers["Prefer"] == "return=representation"
    assert json.loads(request.content) == {"display_name": "Ada Lovelace"}


def test_supabase_token_lookup_includes_display_name() -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/access_tokens"):
            return httpx.Response(
                200,
                json=[{"user_id": "user-one", "expires_at": None, "revoked_at": None}],
                request=request,
            )
        return httpx.Response(
            200,
            json=[{
                "id": "user-one",
                "display_name": "Ada",
                "timezone": "Europe/Istanbul",
                "is_demo": False,
                "demo_expires_at": None,
            }],
            request=request,
        )

    store = SupabasePlanStore("https://example.invalid", "service-key")
    headers = dict(store._client.headers)
    store._client.close()
    store._client = httpx.Client(transport=httpx.MockTransport(handle), headers=headers)
    try:
        user_and_expiry = store.get_user_for_token_hash("hashed-token")
    finally:
        store._client.close()

    assert user_and_expiry is not None
    assert user_and_expiry[0].display_name == "Ada"
    assert requests[1].url.params["select"] == "id,display_name,timezone,is_demo,demo_expires_at"


def test_personalization_is_scoped_and_profile_values_persist(store: ProfileStore) -> None:
    own = patch_personalization(PersonalizationPatch.model_validate({"interests": ["study"], "recommendation_frequency": "weekly"}), AuthenticatedUser("user-one", "Europe/Istanbul", False, None), store)
    assert own["interests"] == ["study"]
    assert get_personalization(AuthenticatedUser("user-two", "Europe/Berlin", False, None), store)["interests"] == ["music"]
    assert store.personalization["user-two"]["interests"] == ["music"]


def test_onboarding_progress_is_user_scoped_and_resumable(store: ProfileStore) -> None:
    saved = patch_personalization(PersonalizationPatch.model_validate({"onboarding_completed": ["interests"], "onboarding_skipped": ["age_range"]}), AuthenticatedUser("user-one", "Europe/Istanbul", False, None), store)
    resumed = get_personalization(AuthenticatedUser("user-one", "Europe/Istanbul", False, None), store)
    assert resumed["onboarding_completed"] == ["interests"]
    assert resumed["onboarding_skipped"] == ["age_range"]
    assert get_personalization(AuthenticatedUser("user-two", "Europe/Berlin", False, None), store)["onboarding_completed"] == []


def test_user_cannot_target_another_users_profile(store: ProfileStore) -> None:
    with pytest.raises(ValidationError):
        PersonalizationPatch.model_validate({"user_id": "user-two", "interests": ["private"]})
    response = delete_profile_field("interests", AuthenticatedUser("user-one", "Europe/Istanbul", False, None), store)
    assert response["user_id"] == "user-one"
    assert store.personalization["user-two"]["interests"] == ["music"]


@pytest.mark.parametrize("payload", [
    {"age_range": "2000-01-01"}, {"life_context": "retired"},
    {"recommendation_frequency": "monthly"}, {"interests": [""]},
    {"interests": None}, {"deadlines_goals": None},
    {"deadlines_goals": [{"title": "Exam", "deadline": "2026-02-30", "kind": "exam"}]},
    {"deadlines_goals": [{"title": "Exam", "extra": "no"}]},
])
def test_personalization_rejects_invalid_data(store: ProfileStore, payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        PersonalizationPatch.model_validate(payload)
    assert store.personalization["user-one"].get("recommendation_frequency") is None


def test_profile_goal_stores_explicit_date_and_kind(store: ProfileStore) -> None:
    payload = PersonalizationPatch.model_validate({"deadlines_goals": [{"title": "Exam", "deadline": "2026-11-02", "kind": "exam"}]})
    response = patch_personalization(payload, AuthenticatedUser("user-one", "Europe/Istanbul", False, None), store)
    assert response["deadlines_goals"] == [{"title": "Exam", "deadline": "2026-11-02", "kind": "exam"}]


def test_shared_schema_defines_the_profile_contract() -> None:
    schema = json.loads((Path(__file__).resolve().parents[2] / "ai/schema.json").read_text())
    profile = schema["$defs"]["PersonalizationProfile"]
    assert set(profile["properties"]) == set(PersonalizationPatch.model_fields) | {"user_id"}
    assert "birth_date" not in profile["properties"]
    assert profile["properties"]["age_range"]["enum"][-1] is None


def test_delete_one_profile_field_only(store: ProfileStore) -> None:
    store.personalization["user-one"].update({"skills_to_develop": ["focus"], "interests": ["running"], "onboarding_completed": ["interests"]})
    response = delete_profile_field("interests", AuthenticatedUser("user-one", "Europe/Istanbul", False, None), store)
    assert response["interests"] == []
    assert response["skills_to_develop"] == ["focus"]
    assert response["onboarding_completed"] == []


def test_clearing_one_profile_answer_removes_its_progress_only(store: ProfileStore) -> None:
    store.personalization["user-one"].update({"preferred_name": "Ada", "interests": ["running"], "onboarding_completed": ["preferred_name", "interests"]})
    response = patch_personalization(PersonalizationPatch.model_validate({"preferred_name": None}), AuthenticatedUser("user-one", "Europe/Istanbul", False, None), store)
    assert response["preferred_name"] is None
    assert response["interests"] == ["running"]
    assert response["onboarding_completed"] == ["interests"]


def test_profile_reset_preserves_account_and_non_profile_data(store: ProfileStore) -> None:
    before = dict(store.keep_data)
    response = reset_personalization(AuthenticatedUser("user-one", "Europe/Istanbul", False, None), store)
    assert response == {"deleted": True}
    assert get_personalization(AuthenticatedUser("user-one", "Europe/Istanbul", False, None), store)["interests"] == []
    assert store.keep_data == before
    assert store.get_user_for_token_hash(_hash(TOKEN_ONE)) is not None


def test_postgrest_personalization_reads_writes_and_deletes_are_user_filtered() -> None:
    captured: list[httpx.Request] = []
    def handle(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        if request.method == "GET": return httpx.Response(200, json=[{"user_id": "user-one", "interests": ["study"]}], request=request)
        if request.method == "POST": return httpx.Response(201, json=[{"user_id": "user-one", "interests": ["study"]}], request=request)
        return httpx.Response(204, request=request)
    store = SupabasePlanStore("https://example.invalid", "service-key")
    headers = dict(store._client.headers); store._client.close()
    store._client = httpx.Client(transport=httpx.MockTransport(handle), headers=headers)
    try:
        assert store.get_personalization(user_id="user-one")["interests"] == ["study"]
        store.update_personalization(user_id="user-one", changes={"user_id": "user-two", "interests": ["study"]})
        store.reset_personalization(user_id="user-one")
    finally:
        store._client.close()
    assert captured[0].url.params["user_id"] == "eq.user-one"
    assert captured[2].url.params["user_id"] == "eq.user-one"
    assert json.loads(captured[1].content)["user_id"] == "user-one"
