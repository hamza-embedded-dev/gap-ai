from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import SecretStr, ValidationError
from starlette.exceptions import HTTPException
from starlette.middleware.cors import CORSMiddleware
import trio

from app.api.demo import DemoSessionResponse, create_demo_session
from app.api.health import HealthResponse, get_health
from app.api.plans import current_user
import app.api.demo as demo_api
import app.api.plans as plans_api
from app.config import Settings
from app.db.plans import AuthenticatedUser, SupabasePlanStore, get_plan_store
from app.main import app as api_app, setup_cors

PEPPER = "p" * 32


class FakeStore:
    def __init__(self) -> None:
        self.tokens: dict[str, tuple[AuthenticatedUser, str | None]] = {}
        self.created_plans: list[dict[str, object]] = []
        self.created_outcomes: list[dict[str, object]] = []
        self.deleted_demo_users: list[str] = []
        self.fail_outcome_creation = False

    def get_user_for_token_hash(self, token_hash: str):
        return self.tokens.get(token_hash)

    def create_plan(self, plan: dict[str, object]) -> dict[str, object]:
        self.created_plans.append(plan)
        return plan

    def list_plans(self, *, user_id: str, from_time=None, to_time=None):
        return [
            {**plan, "latest_outcome": None}
            for plan in self.created_plans
            if plan["user_id"] == user_id
        ]

    def create_outcome(
        self, *, user_id: str, plan_id: str, outcome: dict[str, object]
    ) -> dict[str, object]:
        if self.fail_outcome_creation:
            raise RuntimeError("seed outcome failed")
        row = {**outcome, "user_id": user_id, "plan_id": plan_id}
        self.created_outcomes.append(row)
        return row

    def create_plan_idempotently(self, **kwargs):
        raise NotImplementedError

    def create_demo_session(
        self, *, token_hash: str, created_at: datetime, expires_at: datetime
    ) -> AuthenticatedUser:
        user = AuthenticatedUser(
            id=str(uuid4()),
            timezone="Europe/Istanbul",
            is_demo=True,
            demo_expires_at=expires_at.isoformat(),
        )
        self.tokens[token_hash] = (user, expires_at.isoformat())
        return user

    def delete_demo_session(self, *, user_id: str) -> None:
        self.deleted_demo_users.append(user_id)
        self.tokens = {
            token_hash: value
            for token_hash, value in self.tokens.items()
            if value[0].id != user_id
        }


@pytest.fixture
def fake_store() -> FakeStore:
    return FakeStore()


@pytest.fixture(autouse=True)
def _patch_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = SimpleNamespace(
        token_hash_pepper=SecretStr(PEPPER),
        environment="development",
        allowed_origins=[],
    )
    monkeypatch.setattr(demo_api, "get_settings", lambda: settings)
    monkeypatch.setattr(plans_api, "get_settings", lambda: settings)


# --- 1. Health Tests ---------------------------------------------------------


def test_health_response_matches_contract() -> None:
    response = get_health()
    assert response.status == "ok"
    assert response.version == "0.1.0"
    assert response.model_dump() == {"status": "ok", "version": "0.1.0"}


def test_health_response_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        HealthResponse.model_validate({"status": "ok", "version": "0.1.0", "extra": True})


# --- 2. CORS Configuration Tests ---------------------------------------------


def test_cors_settings_parses_comma_separated_origins() -> None:
    settings = Settings(
        ALLOWED_ORIGINS="http://localhost:3000, https://app.example.com",
        _env_file=None,
    )
    assert settings.allowed_origins == [
        "http://localhost:3000",
        "https://app.example.com",
    ]


def test_cors_settings_parses_json_array_origins() -> None:
    settings = Settings(
        ALLOWED_ORIGINS='["http://localhost:3000", "http://127.0.0.1:3000"]',
        _env_file=None,
    )
    assert settings.allowed_origins == [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]


def test_cors_settings_handles_empty_or_whitespace() -> None:
    assert Settings(ALLOWED_ORIGINS="", _env_file=None).allowed_origins == []
    assert Settings(ALLOWED_ORIGINS="   ", _env_file=None).allowed_origins == []


def test_setup_cors_with_explicit_origins_enables_credentials() -> None:
    app = FastAPI()
    setup_cors(app, ["http://localhost:3000"])
    assert len(app.user_middleware) == 1
    middleware = app.user_middleware[0]
    assert middleware.cls is CORSMiddleware
    assert middleware.kwargs["allow_origins"] == ["http://localhost:3000"]
    assert middleware.kwargs["allow_credentials"] is True


def test_setup_cors_with_wildcard_disables_credentials() -> None:
    app = FastAPI()
    setup_cors(app, ["*"])
    assert len(app.user_middleware) == 1
    middleware = app.user_middleware[0]
    assert middleware.cls is CORSMiddleware
    assert middleware.kwargs["allow_origins"] == ["*"]
    assert middleware.kwargs["allow_credentials"] is False


def test_setup_cors_with_empty_origins_adds_no_middleware() -> None:
    app = FastAPI()
    setup_cors(app, [])
    assert len(app.user_middleware) == 0


# --- 3. Token Issuance / Demo Session Tests -----------------------------------


def test_create_demo_session_issues_token_with_24h_expiry(fake_store: FakeStore) -> None:
    before = datetime.now(timezone.utc)
    response = create_demo_session(fake_store)
    after = datetime.now(timezone.utc)

    # Cryptographically secure bearer token
    assert isinstance(response.token, str)
    assert len(response.token) >= 32
    assert response.is_demo is True

    # 24-hour expiry
    expected_min = before + timedelta(hours=24) - timedelta(seconds=2)
    expected_max = after + timedelta(hours=24) + timedelta(seconds=2)
    assert expected_min <= response.expires_at <= expected_max

    # Raw token must NOT be stored in the database/store
    assert response.token not in fake_store.tokens

    # Only peppered hash is stored
    expected_hash = hashlib.sha256((response.token + PEPPER).encode("utf-8")).hexdigest()
    assert expected_hash in fake_store.tokens
    user, expires_at_str = fake_store.tokens[expected_hash]
    assert user.is_demo is True
    assert user.timezone == "Europe/Istanbul"
    assert user.demo_expires_at == response.expires_at.isoformat()

    # Response does NOT leak the hash
    dumped = response.model_dump()
    assert "token_hash" not in dumped
    assert set(dumped.keys()) == {"token", "expires_at", "is_demo"}
    assert len(fake_store.created_plans) == 22
    assert fake_store.created_outcomes
    assert {plan["user_id"] for plan in fake_store.created_plans} == {user.id}
    assert {outcome["user_id"] for outcome in fake_store.created_outcomes} == {user.id}


def test_issued_demo_token_authenticates_with_current_user(fake_store: FakeStore) -> None:
    session = create_demo_session(fake_store)
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=session.token)
    user = current_user(creds, fake_store)
    assert user.is_demo is True
    assert user.timezone == "Europe/Istanbul"
    response = plans_api.list_plans(user, fake_store)
    assert len(response["items"]) == 22
    assert all(plan["latest_outcome"] is None for plan in response["items"])


def test_create_demo_session_fails_closed_without_pepper(
    fake_store: FakeStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        demo_api,
        "get_settings",
        lambda: SimpleNamespace(token_hash_pepper=None),
    )
    with pytest.raises(HTTPException) as exc_info:
        create_demo_session(fake_store)
    assert exc_info.value.status_code == 500


def test_demo_seed_failure_deletes_the_new_demo_user(fake_store: FakeStore) -> None:
    fake_store.fail_outcome_creation = True

    with pytest.raises(RuntimeError, match="seed outcome failed"):
        create_demo_session(fake_store)

    assert len(fake_store.deleted_demo_users) == 1
    assert not fake_store.tokens


# --- 4. ASGI Integration Tests (Windows skipped due to sandbox socket-pair) ---

_skip_windows = pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows socket-pair initialization is blocked in this sandbox; covered by Linux CI",
)


@_skip_windows
def test_asgi_get_health_returns_200() -> None:
    async def request() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=api_app), base_url="http://test"
        ) as client:
            return await client.get("/health")

    response = trio.run(request)
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "0.1.0"}


@_skip_windows
def test_asgi_post_demo_session_returns_201(fake_store: FakeStore) -> None:
    api_app.dependency_overrides[get_plan_store] = lambda: fake_store
    try:
        async def request() -> httpx.Response:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=api_app), base_url="http://test"
            ) as client:
                return await client.post("/demo/session")

        response = trio.run(request)
        assert response.status_code == 201
        data = response.json()
        assert "token" in data
        assert data["is_demo"] is True
        assert "expires_at" in data
        assert len(data["token"]) >= 32
    finally:
        api_app.dependency_overrides.clear()


# --- 5. SupabasePlanStore MockTransport Tests ---------------------------------


def test_supabase_create_demo_session_carries_fields_and_tokens() -> None:
    captured_requests: list[httpx.Request] = []
    user_id = str(uuid4())
    mock_token_hash = "mock_hash_" + "a" * 54
    created = datetime.now(timezone.utc)
    expires = created + timedelta(hours=24)

    def handle(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        if request.url.path == "/rest/v1/users":
            assert request.method == "POST"
            assert request.headers["Prefer"] == "return=representation"
            assert request.headers["apikey"] == "test-service-key"
            assert request.headers["Authorization"] == "Bearer test-service-key"
            body = json.loads(request.content)
            assert body["timezone"] == "Europe/Istanbul"
            assert body["is_demo"] is True
            assert body["display_name"] == "Demo User"
            assert body["created_at"] == created.isoformat()
            assert body["demo_expires_at"] == expires.isoformat()
            return httpx.Response(
                201,
                json=[
                    {
                        "id": user_id,
                        "timezone": "Europe/Istanbul",
                        "is_demo": True,
                        "demo_expires_at": expires.isoformat(),
                    }
                ],
                request=request,
            )
        elif request.url.path == "/rest/v1/access_tokens":
            assert request.method == "POST"
            assert request.headers["Prefer"] == "return=representation"
            body = json.loads(request.content)
            assert body["user_id"] == user_id
            assert body["token_hash"] == mock_token_hash
            assert body["created_at"] == created.isoformat()
            assert body["expires_at"] == expires.isoformat()
            return httpx.Response(201, json=[{"id": str(uuid4())}], request=request)
        return httpx.Response(404, request=request)

    store = SupabasePlanStore("https://example.invalid", "test-service-key")
    headers = dict(store._client.headers)
    store._client.close()
    store._client = httpx.Client(transport=httpx.MockTransport(handle), headers=headers)
    try:
        user = store.create_demo_session(
            token_hash=mock_token_hash,
            created_at=created,
            expires_at=expires,
        )
    finally:
        store._client.close()

    assert len(captured_requests) == 2
    assert user.id == user_id
    assert user.timezone == "Europe/Istanbul"
    assert user.is_demo is True
    assert user.demo_expires_at == expires.isoformat()


def test_supabase_create_demo_session_handles_user_creation_error() -> None:
    calls = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500, json={"message": "database error"}, request=request)

    store = SupabasePlanStore("https://example.invalid", "test-service-key")
    store._client.close()
    store._client = httpx.Client(transport=httpx.MockTransport(handle))
    try:
        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            store.create_demo_session(
                token_hash="hash",
                created_at=datetime.now(timezone.utc),
                expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
            )
        assert exc_info.value.response.status_code == 500
        assert calls == 1
    finally:
        store._client.close()


def test_supabase_create_demo_session_handles_token_creation_error() -> None:
    calls = 0
    expires = datetime.now(timezone.utc) + timedelta(hours=24)

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if request.url.path == "/rest/v1/users":
            return httpx.Response(
                201,
                json=[
                    {
                        "id": "user-123",
                        "timezone": "Europe/Istanbul",
                        "is_demo": True,
                        "demo_expires_at": expires.isoformat(),
                    }
                ],
                request=request,
            )
        return httpx.Response(409, json={"code": "23505", "message": "conflict"}, request=request)

    store = SupabasePlanStore("https://example.invalid", "test-service-key")
    store._client.close()
    store._client = httpx.Client(transport=httpx.MockTransport(handle))
    try:
        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            store.create_demo_session(
                token_hash="hash",
                created_at=datetime.now(timezone.utc),
                expires_at=expires,
            )
        assert exc_info.value.response.status_code == 409
        assert calls == 2
    finally:
        store._client.close()

