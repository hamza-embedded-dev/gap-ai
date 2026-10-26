import hashlib
from types import SimpleNamespace
from unittest.mock import MagicMock

from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.api.plans import current_user
from app.db.plans import AuthenticatedUser, get_plan_store
from app.main import app


def test_feedback_is_user_scoped_and_validated(monkeypatch):
    pepper = "p" * 32
    monkeypatch.setattr("app.api.plans.get_settings", lambda: SimpleNamespace(token_hash_pepper=SecretStr(pepper)))
    users = {hashlib.sha256((t+pepper).encode()).hexdigest(): AuthenticatedUser(uid, "Europe/Istanbul", False, None) for t, uid in (("a", "A"), ("b", "B"))}
    rows = []
    store = MagicMock()
    store.get_user_for_token_hash.side_effect = lambda h: (users[h], None) if h in users else None
    store.save_recommendation_feedback.side_effect = lambda uid, payload: (rows.append({**payload, "user_id":uid}) or rows[-1])
    store.list_recommendation_feedback.side_effect = lambda uid: [r for r in rows if r["user_id"] == uid]
    app.dependency_overrides[get_plan_store] = lambda: store
    try:
        client = TestClient(app)
        body = {"recommendation_id":"discovery-walk", "action":"dismissed", "rating":None, "payload":{}}
        assert client.post("/recommendations/feedback", json=body, headers={"Authorization":"Bearer a"}).status_code == 201
        assert store.list_recommendation_feedback("A")[0]["user_id"] == "A"
        assert store.list_recommendation_feedback("B") == []
        assert client.post("/recommendations/feedback", json={**body,"recommendation_id":""}, headers={"Authorization":"Bearer b"}).status_code == 422
    finally:
        app.dependency_overrides.clear()
