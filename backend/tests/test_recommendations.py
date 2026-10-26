from datetime import datetime, timedelta, timezone

from app.recommendations import apply_policy, dedup_key


def test_discovery_works_without_history_and_is_labeled():
    cards = apply_policy([], [])
    assert len(cards) == 3
    assert all(c["source"] == "discovery" and c["label"] == "Not based on your history" for c in cards)
    assert all(c["confidence"] == "none" for c in cards)
    assert all(c["evidence"] == {} for c in cards)


def test_policy_caps_and_deduplicates_and_recent_dismissal_hides():
    behavior = [{"id": "b1", "title": "B", "message": "M", "why": "W", "evidence": {}, "confidence": "moderate", "next_step": "N"}]
    now = datetime.now(timezone.utc)
    feedback = [{"recommendation_id": "discovery-walk", "action": "dismissed", "created_at": (now-timedelta(days=1)).isoformat()}]
    cards = apply_policy(behavior, feedback, now=now)
    assert len(cards) <= 3
    assert "discovery-walk" not in [c["id"] for c in cards]
    assert all(c["dedup_key"] == dedup_key(c) for c in cards)


def test_useful_feedback_changes_selection_order():
    feedback = [{"recommendation_id": "discovery-experience", "rating": "useful"}]
    assert apply_policy([], feedback)[0]["id"] == "discovery-experience"


def test_dismissal_window_expires():
    old = datetime.now(timezone.utc)-timedelta(days=31)
    cards = apply_policy([], [{"recommendation_id":"discovery-walk", "action":"dismissed", "created_at":old.isoformat()}])
    assert "discovery-walk" in [c["id"] for c in cards]
    assert len(cards) <= 3

