from __future__ import annotations

import hashlib
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
import trio
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import SecretStr

import app.api.plans as plans_api
import app.db.plans as db_plans
from app.api.errors import APIError
from app.db.plans import AuthenticatedUser, get_plan_store
from app.main import app as api_app

PEPPER = "p" * 32
TOKEN = "raw-token-value"
TOKEN_HASH = hashlib.sha256((TOKEN + PEPPER).encode("utf-8")).hexdigest()


def _iso(delta: timedelta) -> str:
    return (datetime.now(timezone.utc) + delta).isoformat()


def _user(**changes: object) -> AuthenticatedUser:
    values: dict[str, object] = {
        "id": "user-one",
        "timezone": "Europe/Istanbul",
        "is_demo": False,
        "demo_expires_at": None,
    }
    values.update(changes)
    return AuthenticatedUser(**values)  # type: ignore[arg-type]


class TokenStore:
    """Minimal store: maps token hashes to (user, token_expires_at)."""

    def __init__(self, tokens: dict[str, tuple[AuthenticatedUser, str | None]]) -> None:
        self.tokens = tokens
        self.lookups: list[str] = []
        self.created: list[dict[str, object]] = []
        self.requests: dict[tuple[str, str], tuple[str, dict[str, object]]] = {}

    def get_user_for_token_hash(self, token_hash: str):
        self.lookups.append(token_hash)
        return self.tokens.get(token_hash)

    def create_plan(self, plan: dict[str, object]) -> dict[str, object]:
        return self._snapshot(plan)

    def create_plan_idempotently(self, *, user_id, idempotency_key, request_hash, plan):
        key = (user_id, idempotency_key)
        if key in self.requests:
            saved_hash, snapshot = self.requests[key]
            return snapshot, saved_hash != request_hash
        snapshot = self._snapshot(plan)
        self.requests[key] = (request_hash, snapshot)
        return snapshot, False

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

    def _snapshot(self, plan: dict[str, object]) -> dict[str, object]:
        self.created.append(plan)
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


def _settings(pepper: str | None = PEPPER) -> SimpleNamespace:
    return SimpleNamespace(token_hash_pepper=SecretStr(pepper) if pepper else None)


@pytest.fixture(autouse=True)
def _pepper(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(plans_api, "get_settings", lambda: _settings())


def _credentials(token: str = TOKEN) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


def _assert_unauthorized(call) -> None:
    with pytest.raises(APIError) as error:
        call()
    assert error.value.status_code == 401
    assert error.value.error == "unauthorized"


# --- current_user -----------------------------------------------------------


def test_current_user_accepts_valid_token() -> None:
    user = _user()
    store = TokenStore({TOKEN_HASH: (user, _iso(timedelta(hours=1)))})

    assert plans_api.current_user(_credentials(), store) == user
    assert store.lookups == [TOKEN_HASH]


def test_current_user_accepts_valid_token_without_expiry() -> None:
    store = TokenStore({TOKEN_HASH: (_user(), None)})

    assert plans_api.current_user(_credentials(), store) == _user()


def test_current_user_rejects_unknown_token() -> None:
    store = TokenStore({TOKEN_HASH: (_user(), None)})

    _assert_unauthorized(lambda: plans_api.current_user(_credentials("other"), store))


def test_current_user_rejects_missing_credentials() -> None:
    store = TokenStore({})

    _assert_unauthorized(lambda: plans_api.current_user(None, store))
    assert store.lookups == []


def test_current_user_rejects_expired_token() -> None:
    store = TokenStore({TOKEN_HASH: (_user(), _iso(timedelta(seconds=-1)))})

    _assert_unauthorized(lambda: plans_api.current_user(_credentials(), store))


def test_current_user_rejects_expired_demo_session() -> None:
    demo = _user(is_demo=True, demo_expires_at=_iso(timedelta(seconds=-1)))
    store = TokenStore({TOKEN_HASH: (demo, None)})

    _assert_unauthorized(lambda: plans_api.current_user(_credentials(), store))


def test_current_user_accepts_active_demo_session() -> None:
    demo = _user(is_demo=True, demo_expires_at=_iso(timedelta(hours=1)))
    store = TokenStore({TOKEN_HASH: (demo, None)})

    assert plans_api.current_user(_credentials(), store) == demo


def test_current_user_rejects_demo_user_without_expiry() -> None:
    store = TokenStore({TOKEN_HASH: (_user(is_demo=True), None)})

    _assert_unauthorized(lambda: plans_api.current_user(_credentials(), store))


def test_current_user_rejects_when_pepper_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(plans_api, "get_settings", lambda: _settings(None))
    store = TokenStore({TOKEN_HASH: (_user(), None)})

    _assert_unauthorized(lambda: plans_api.current_user(_credentials(), store))
    assert store.lookups == []


# --- get_plan_store configuration ------------------------------------------


def test_get_plan_store_does_not_require_supabase_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        db_plans,
        "get_settings",
        lambda: SimpleNamespace(supabase_url=None, supabase_service_key=None),
    )
    db_plans._build_plan_store.cache_clear()
    get_plan_store.cache_clear()
    try:
        store = get_plan_store()  # must not raise during dependency resolution
        with pytest.raises(RuntimeError, match="SUPABASE_URL"):
            store.get_user_for_token_hash("hash")
    finally:
        db_plans._build_plan_store.cache_clear()
        get_plan_store.cache_clear()


# --- POST /plans over ASGI --------------------------------------------------

_skip_windows = pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows socket-pair initialization is blocked in this sandbox; covered by Linux CI",
)

_PARSED = {
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


def _post(headers: dict[str, str] | None, body: dict[str, object]) -> httpx.Response:
    async def request() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=api_app), base_url="http://test"
        ) as client:
            return await client.post("/plans", json=body, headers=headers or {})

    return trio.run(request)


@pytest.fixture
def store():
    token_store = TokenStore({TOKEN_HASH: (_user(), None)})
    api_app.dependency_overrides[get_plan_store] = lambda: token_store
    yield token_store
    api_app.dependency_overrides.clear()


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


@_skip_windows
def test_post_plans_without_authorization_returns_401_without_supabase_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # No dependency override: the real (lazy) store must not 500 before auth.
    monkeypatch.setattr(
        db_plans,
        "get_settings",
        lambda: SimpleNamespace(supabase_url=None, supabase_service_key=None),
    )
    db_plans._build_plan_store.cache_clear()
    get_plan_store.cache_clear()
    try:
        response = _post(None, {"parsed_plan": _PARSED, "source": "text"})
    finally:
        db_plans._build_plan_store.cache_clear()
        get_plan_store.cache_clear()

    assert response.status_code == 401
    assert response.json()["error"] == "unauthorized"


@_skip_windows
def test_post_plans_with_unknown_token_returns_401(store: TokenStore) -> None:
    response = _post(
        {"Authorization": "Bearer unknown"}, {"parsed_plan": _PARSED, "source": "text"}
    )

    assert response.status_code == 401
    assert response.json()["error"] == "unauthorized"
    assert store.created == []


@_skip_windows
def test_post_plans_creates_plan_with_201(store: TokenStore) -> None:
    response = _post(_auth(), {"parsed_plan": _PARSED, "source": "text"})

    assert response.status_code == 201
    body = response.json()
    assert body["title"] == "Run"
    assert body["latest_outcome"] is None
    assert body["planned_start"].startswith("2026-10-15T18:30:00")
    assert len(store.created) == 1


@_skip_windows
def test_post_plans_invalid_body_returns_contract_422(store: TokenStore) -> None:
    response = _post(_auth(), {"parsed_plan": _PARSED, "source": "text", "extra": 1})

    assert response.status_code == 422
    assert response.json()["error"] == "validation_error"
    assert store.created == []


@_skip_windows
def test_post_plans_non_create_intent_returns_422(store: TokenStore) -> None:
    parsed = {
        **_PARSED,
        "intent": "clarify",
        "title": None,
        "category": None,
        "date": None,
        "time": None,
        "duration_minutes": None,
        "clarification_question": "Which day?",
    }
    response = _post(_auth(), {"parsed_plan": parsed, "source": "text"})

    assert response.status_code == 422
    assert response.json()["error"] == "validation_error"
    assert store.created == []


@_skip_windows
def test_post_plans_idempotency_replay_and_conflict(store: TokenStore) -> None:
    headers = {**_auth(), "Idempotency-Key": "key-1"}
    body = {"parsed_plan": _PARSED, "source": "text"}

    first = _post(headers, body)
    replay = _post(headers, body)
    conflict = _post(headers, {"parsed_plan": {**_PARSED, "title": "Study"}, "source": "text"})

    assert first.status_code == 201
    assert replay.status_code == 201
    assert replay.json() == first.json()
    assert len(store.created) == 1
    assert conflict.status_code == 422
    assert conflict.json()["error"] == "validation_error"
