from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.api.errors import APIError
from app.api.plans import current_user
from app.db.plans import AuthenticatedUser, SupabasePlanStore, get_plan_store
from app.main import app
from fastapi.security import HTTPAuthorizationCredentials


MOCK_JWT = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3OC0xMjM0LTU2NzgtMTIzNC01Njc4MTIzNDU2NzgiLCJlbWFpbCI6Imdvb2dsZS11c2VyQGV4YW1wbGUuY29tIiwicm9sZSI6ImF1dGhlbnRpY2F0ZWQifQ.fake_signature"
MOCK_USER_ID = "12345678-1234-5678-1234-567812345678"


class MockJWTStore:
    """Mock store supporting both token hash and Supabase JWT lookups."""

    def __init__(self) -> None:
        self.jwt_users: dict[str, AuthenticatedUser] = {}
        self.token_hash_users: dict[str, tuple[AuthenticatedUser, str | None]] = {}

    def get_user_for_supabase_jwt(self, jwt_token: str) -> AuthenticatedUser | None:
        return self.jwt_users.get(jwt_token)

    def get_user_for_token_hash(
        self, token_hash: str
    ) -> tuple[AuthenticatedUser, str | None] | None:
        return self.token_hash_users.get(token_hash)


def _make_auth_user(
    user_id: str = MOCK_USER_ID,
    display_name: str = "Google User",
    timezone_name: str = "Europe/Istanbul",
) -> AuthenticatedUser:
    return AuthenticatedUser(
        id=user_id,
        timezone=timezone_name,
        is_demo=False,
        demo_expires_at=None,
        display_name=display_name,
    )


def test_current_user_with_valid_supabase_jwt() -> None:
    store = MockJWTStore()
    user = _make_auth_user()
    store.jwt_users[MOCK_JWT] = user

    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=MOCK_JWT)
    resolved = current_user(credentials=creds, store=store)
    assert resolved == user
    assert resolved.id == MOCK_USER_ID
    assert resolved.display_name == "Google User"


def test_current_user_with_invalid_supabase_jwt() -> None:
    store = MockJWTStore()
    # No user mapped for MOCK_JWT
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=MOCK_JWT)
    with pytest.raises(APIError) as exc_info:
        current_user(credentials=creds, store=store)
    assert exc_info.value.status_code == 401
    assert exc_info.value.error == "unauthorized"


def test_current_user_with_missing_credentials() -> None:
    store = MockJWTStore()
    with pytest.raises(APIError) as exc_info:
        current_user(credentials=None, store=store)
    assert exc_info.value.status_code == 401
    assert exc_info.value.error == "unauthorized"


def test_supabase_plan_store_jwt_validation_with_existing_user() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        url_str = str(request.url)
        if "/auth/v1/user" in url_str:
            assert request.headers.get("Authorization") == f"Bearer {MOCK_JWT}"
            return httpx.Response(
                200,
                json={
                    "id": MOCK_USER_ID,
                    "email": "user@gmail.com",
                    "user_metadata": {"full_name": "Verified Google User"},
                },
            )
        if "/rest/v1/users" in url_str and request.method == "GET":
            return httpx.Response(
                200,
                json=[
                    {
                        "id": MOCK_USER_ID,
                        "display_name": "Verified Google User",
                        "timezone": "Europe/Istanbul",
                        "is_demo": False,
                        "demo_expires_at": None,
                    }
                ],
            )
        return httpx.Response(404)

    store = SupabasePlanStore("https://example.supabase.co", "test-service-key")
    store._client = httpx.Client(transport=httpx.MockTransport(handler))

    user = store.get_user_for_supabase_jwt(MOCK_JWT)
    assert user is not None
    assert user.id == MOCK_USER_ID
    assert user.display_name == "Verified Google User"
    assert user.timezone == "Europe/Istanbul"
    assert not user.is_demo


def test_supabase_plan_store_jwt_validation_auto_provisions_new_user() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        url_str = str(request.url)
        if "/auth/v1/user" in url_str:
            return httpx.Response(
                200,
                json={
                    "id": MOCK_USER_ID,
                    "email": "newuser@gmail.com",
                    "user_metadata": {"name": "New Google User"},
                },
            )
        if "/rest/v1/users" in url_str and request.method == "GET":
            # First query: user does not exist in public.users yet
            return httpx.Response(200, json=[])
        if "/rest/v1/users" in url_str and request.method == "POST":
            # Auto-provision POST
            body = json.loads(request.content.decode("utf-8"))
            calls.append(body)
            return httpx.Response(
                201,
                json=[
                    {
                        "id": body["id"],
                        "display_name": body["display_name"],
                        "timezone": body["timezone"],
                        "is_demo": body["is_demo"],
                        "demo_expires_at": None,
                    }
                ],
            )
        return httpx.Response(404)

    store = SupabasePlanStore("https://example.supabase.co", "test-service-key")
    store._client = httpx.Client(transport=httpx.MockTransport(handler))

    user = store.get_user_for_supabase_jwt(MOCK_JWT)
    assert user is not None
    assert user.id == MOCK_USER_ID
    assert user.display_name == "New Google User"
    assert len(calls) == 1
    assert calls[0]["id"] == MOCK_USER_ID


def test_supabase_plan_store_jwt_validation_rejected_by_supabase_auth() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "/auth/v1/user" in str(request.url):
            return httpx.Response(401, json={"message": "Invalid JWT: signature verification failed"})
        return httpx.Response(404)

    store = SupabasePlanStore("https://example.supabase.co", "test-service-key")
    store._client = httpx.Client(transport=httpx.MockTransport(handler))

    user = store.get_user_for_supabase_jwt("invalid.jwt.token")
    assert user is None


def test_api_endpoint_protected_with_supabase_jwt() -> None:
    store = MockJWTStore()
    user = _make_auth_user()
    store.jwt_users[MOCK_JWT] = user

    app.dependency_overrides[get_plan_store] = lambda: store
    try:
        client = TestClient(app)

        # Calling /me with valid Supabase JWT
        res = client.get("/me", headers={"Authorization": f"Bearer {MOCK_JWT}"})
        assert res.status_code == 200
        data = res.json()
        assert data["id"] == MOCK_USER_ID
        assert data["display_name"] == "Google User"

        # Calling /me with invalid JWT
        bad_res = client.get("/me", headers={"Authorization": "Bearer eyJbad.invalid.jwt"})
        assert bad_res.status_code == 401
        assert bad_res.json()["error"] == "unauthorized"

        # Calling /me without headers
        unauth_res = client.get("/me")
        assert unauth_res.status_code == 401
    finally:
        app.dependency_overrides.pop(get_plan_store, None)
