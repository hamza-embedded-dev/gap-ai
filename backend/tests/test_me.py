from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.db.plans import AuthenticatedUser, SupabasePlanStore, get_plan_store
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

    def get_user_for_token_hash(self, token_hash: str):
        return self.tokens.get(token_hash)

    def update_profile(self, *, user_id: str, changes: dict[str, object]):
        self.updates.append((user_id, changes))
        profile = self.profiles.get(user_id)
        if profile is None:
            return None
        profile.update(changes)
        return dict(profile)


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
