from __future__ import annotations

import hashlib
import json
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
from scripts import create_access_token as token_script

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
        self.plans: dict[str, dict[str, object]] = {}
        self.plan_owners: dict[str, str] = {}

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
        self.plans[str(snapshot["id"])] = snapshot
        self.plan_owners[str(snapshot["id"])] = user_id
        return snapshot, False

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
        return True

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


def _get(
    headers: dict[str, str] | None = None,
    params: dict[str, str] | None = None,
) -> httpx.Response:
    async def request() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=api_app), base_url="http://test"
        ) as client:
            return await client.get("/plans", headers=headers or {}, params=params)

    return trio.run(request)


def _put(path: str, body: dict[str, object], token: str = TOKEN) -> httpx.Response:
    async def request() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=api_app), base_url="http://test"
        ) as client:
            return await client.put(path, json=body, headers={"Authorization": f"Bearer {token}"})

    return trio.run(request)


def _delete(path: str, token: str = TOKEN) -> httpx.Response:
    async def request() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=api_app), base_url="http://test"
        ) as client:
            return await client.delete(path, headers={"Authorization": f"Bearer {token}"})

    return trio.run(request)


@pytest.fixture
def store():
    other_token = "other-user-token"
    other_hash = hashlib.sha256((other_token + PEPPER).encode("utf-8")).hexdigest()
    token_store = TokenStore({
        TOKEN_HASH: (_user(), None),
        other_hash: (_user(id="user-two"), None),
    })
    api_app.dependency_overrides[get_plan_store] = lambda: token_store
    yield token_store
    api_app.dependency_overrides.clear()


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


def _create_owned_plan(store: TokenStore) -> dict[str, object]:
    plan, replayed = store.create_plan_idempotently(
        user_id="user-one",
        idempotency_key=str(uuid4()),
        request_hash="hash",
        plan={
            "title": "Run", "category": "sport",
            "planned_start": "2026-10-15T18:30:00+03:00",
            "planned_end": "2026-10-15T19:30:00+03:00",
            "recurrence_rule": None, "source": "text",
        },
    )
    assert not replayed
    return plan


@_skip_windows
def test_plan_mutation_routes_require_owner_and_persist_changes(store: TokenStore) -> None:
    plan = _create_owned_plan(store)
    plan_id = str(plan["id"])
    body = {
        "title": "Updated Run", "category": "health",
        "planned_start": "2026-10-15T20:00:00+03:00",
        "planned_end": "2026-10-15T21:00:00+03:00",
    }

    updated = _put(f"/plans/{plan_id}", body)
    assert updated.status_code == 200
    assert updated.json()["title"] == "Updated Run"
    assert store.plans[plan_id]["category"] == "health"

    wrong_owner_token = "other-user-token"
    denied_update = _put(f"/plans/{plan_id}", {**body, "title": "Intrusion"}, wrong_owner_token)
    denied_delete = _delete(f"/plans/{plan_id}", wrong_owner_token)
    assert denied_update.status_code == 404
    assert denied_delete.status_code == 404
    assert store.plans[plan_id]["title"] == "Updated Run"

    deleted = _delete(f"/plans/{plan_id}")
    assert deleted.status_code == 204
    assert plan_id not in store.plans
    assert _delete(f"/plans/{plan_id}").status_code == 404


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
def test_get_plans_without_authorization_returns_401_without_supabase_config(
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
        response = _get(None)
    finally:
        db_plans._build_plan_store.cache_clear()
        get_plan_store.cache_clear()

    assert response.status_code == 401
    assert response.json()["error"] == "unauthorized"


@_skip_windows
def test_get_plans_with_unknown_token_returns_401(store: TokenStore) -> None:
    response = _get({"Authorization": "Bearer unknown"})

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


# --- scripts/create_access_token.py ------------------------------------------


SCRIPT_USER_ID = "5f0c6a8e-6b8f-4b0a-9a51-3f1b8f6e2d11"


class FakeSupabase:
    """Records PostgREST calls made by the token script and answers them."""

    def __init__(
        self,
        users: dict[str, dict[str, object]] | None = None,
        token_status: int = 201,
    ) -> None:
        self.users = users or {}
        self.token_status = token_status
        self.requests: list[httpx.Request] = []
        self.tokens: list[dict[str, object]] = []
        self.deleted_users: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        table = request.url.path.removeprefix("/rest/v1/")
        user_filter = request.url.params.get("id", "").removeprefix("eq.")
        if table == "users" and request.method == "GET":
            user = self.users.get(user_filter)
            return httpx.Response(200, json=[user] if user else [])
        if table == "users" and request.method == "POST":
            body = json.loads(request.content)
            user = {"id": SCRIPT_USER_ID, "display_name": body["display_name"], "is_demo": False}
            self.users[SCRIPT_USER_ID] = user
            return httpx.Response(201, json=[user])
        if table == "users" and request.method == "DELETE":
            self.deleted_users.append(user_filter)
            self.users.pop(user_filter, None)
            return httpx.Response(204)
        if table == "access_tokens" and request.method == "POST":
            if self.token_status >= 400:
                return httpx.Response(self.token_status, json={"message": "insert failed"})
            self.tokens.append(json.loads(request.content))
            return httpx.Response(201)
        return httpx.Response(404)

    def admin(self) -> token_script.TokenAdmin:
        return token_script.TokenAdmin(
            "https://db.example", "service-key", transport=httpx.MockTransport(self.handler)
        )

    def methods(self) -> list[tuple[str, str]]:
        return [(r.method, r.url.path) for r in self.requests]


def _script_settings(**changes: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "token_hash_pepper": SecretStr(PEPPER),
        "supabase_url": "https://db.example",
        "supabase_service_key": SecretStr("service-key"),
    }
    values.update(changes)
    return SimpleNamespace(**values)


def test_script_token_hash_matches_current_user() -> None:
    fake = FakeSupabase()
    issued = token_script.issue_token(fake.admin(), pepper=PEPPER, display_name="ESP32")

    stored_hash = fake.tokens[0]["token_hash"]
    store = TokenStore({stored_hash: (_user(id=issued.user_id), None)})
    user = plans_api.current_user(_credentials(issued.token), store)

    assert user.id == issued.user_id


def test_script_creates_user_and_stores_only_the_hash() -> None:
    fake = FakeSupabase()
    issued = token_script.issue_token(
        fake.admin(),
        pepper=PEPPER,
        display_name="ESP32 Ahmet",
        timezone_name="Europe/Berlin",
        generate_token=lambda: "raw-secret-token",
    )

    assert fake.methods() == [("POST", "/rest/v1/users"), ("POST", "/rest/v1/access_tokens")]
    assert json.loads(fake.requests[0].content) == {
        "display_name": "ESP32 Ahmet",
        "timezone": "Europe/Berlin",
    }
    assert fake.tokens == [
        {
            "user_id": SCRIPT_USER_ID,
            "token_hash": token_script.hash_token("raw-secret-token", PEPPER),
            "expires_at": None,
        }
    ]
    for request in fake.requests:
        assert "raw-secret-token" not in str(request.url)
        assert b"raw-secret-token" not in request.content
    assert issued.token == "raw-secret-token"
    assert issued.user_id == SCRIPT_USER_ID


def test_script_issues_token_for_existing_user_with_expiry() -> None:
    fake = FakeSupabase({SCRIPT_USER_ID: {"id": SCRIPT_USER_ID, "display_name": "Ada", "is_demo": False}})
    expires_at = datetime(2026, 11, 1, tzinfo=timezone.utc)

    issued = token_script.issue_token(
        fake.admin(), pepper=PEPPER, user_id=SCRIPT_USER_ID, expires_at=expires_at
    )

    assert fake.methods() == [("GET", "/rest/v1/users"), ("POST", "/rest/v1/access_tokens")]
    assert fake.requests[0].url.params["id"] == f"eq.{SCRIPT_USER_ID}"
    assert fake.tokens[0]["user_id"] == SCRIPT_USER_ID
    assert fake.tokens[0]["expires_at"] == expires_at.isoformat()
    assert issued.display_name == "Ada"


def test_script_rejects_unknown_user_without_writing() -> None:
    fake = FakeSupabase()

    with pytest.raises(token_script.TokenIssueError, match="does not exist"):
        token_script.issue_token(fake.admin(), pepper=PEPPER, user_id=SCRIPT_USER_ID)

    assert fake.methods() == [("GET", "/rest/v1/users")]


def test_script_refuses_demo_users() -> None:
    fake = FakeSupabase({SCRIPT_USER_ID: {"id": SCRIPT_USER_ID, "display_name": "Demo", "is_demo": True}})

    with pytest.raises(token_script.TokenIssueError, match="Demo users"):
        token_script.issue_token(fake.admin(), pepper=PEPPER, user_id=SCRIPT_USER_ID)

    assert fake.tokens == []


def test_script_removes_new_user_when_token_insert_fails() -> None:
    fake = FakeSupabase(token_status=409)

    with pytest.raises(httpx.HTTPStatusError):
        token_script.issue_token(fake.admin(), pepper=PEPPER, display_name="ESP32")

    assert fake.deleted_users == [SCRIPT_USER_ID]
    assert fake.users == {}


def test_script_main_prints_only_the_token_on_stdout(capsys: pytest.CaptureFixture[str]) -> None:
    fake = FakeSupabase()

    code = token_script.main(
        ["--display-name", "ESP32", "--expires-days", "30"],
        settings=_script_settings(),
        transport=httpx.MockTransport(fake.handler),
    )

    out, err = capsys.readouterr()
    token = out.strip()
    assert code == 0
    assert token and "\n" not in token
    assert fake.tokens[0]["token_hash"] == token_script.hash_token(token, PEPPER)
    assert SCRIPT_USER_ID in err
    assert "service-key" not in out + err
    expires_at = datetime.fromisoformat(fake.tokens[0]["expires_at"])
    assert timedelta(days=29) < expires_at - datetime.now(timezone.utc) <= timedelta(days=30)


def test_script_main_requires_pepper_and_supabase(capsys: pytest.CaptureFixture[str]) -> None:
    fake = FakeSupabase()
    transport = httpx.MockTransport(fake.handler)

    no_pepper = token_script.main(
        ["--display-name", "x"], settings=_script_settings(token_hash_pepper=None), transport=transport
    )
    no_db = token_script.main(
        ["--display-name", "x"], settings=_script_settings(supabase_url=None), transport=transport
    )

    err = capsys.readouterr().err
    assert (no_pepper, no_db) == (1, 1)
    assert "TOKEN_HASH_PEPPER" in err and "SUPABASE_URL" in err
    assert fake.requests == []


def test_script_main_reports_supabase_errors(capsys: pytest.CaptureFixture[str]) -> None:
    fake = FakeSupabase(token_status=500)

    code = token_script.main(
        ["--display-name", "ESP32"],
        settings=_script_settings(),
        transport=httpx.MockTransport(fake.handler),
    )

    out, err = capsys.readouterr()
    assert code == 1
    assert out == ""
    assert "HTTP 500: insert failed" in err


@pytest.mark.parametrize(
    "argv",
    [
        ["--user-id", "not-a-uuid"],
        ["--display-name", "x", "--timezone", "Mars/Olympus"],
        ["--user-id", SCRIPT_USER_ID, "--timezone", "Europe/Berlin"],
        ["--display-name", "x", "--expires-days", "0"],
        ["--user-id", SCRIPT_USER_ID, "--display-name", "x"],
        [],
    ],
)
def test_script_main_rejects_invalid_arguments(argv: list[str]) -> None:
    fake = FakeSupabase()

    with pytest.raises(SystemExit) as exit_info:
        token_script.main(argv, settings=_script_settings(), transport=httpx.MockTransport(fake.handler))

    assert exit_info.value.code == 2
    assert fake.requests == []


@_skip_windows
def test_script_token_can_create_a_plan() -> None:
    fake = FakeSupabase()
    issued = token_script.issue_token(fake.admin(), pepper=PEPPER, display_name="ESP32")
    token_store = TokenStore({fake.tokens[0]["token_hash"]: (_user(id=issued.user_id), None)})
    api_app.dependency_overrides[get_plan_store] = lambda: token_store
    try:
        response = _post(
            {"Authorization": f"Bearer {issued.token}"},
            {"parsed_plan": _PARSED, "source": "device"},
        )
    finally:
        api_app.dependency_overrides.clear()

    assert response.status_code == 201
    assert token_store.created[0]["user_id"] == issued.user_id
