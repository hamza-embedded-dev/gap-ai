from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from jsonschema import validate
from app.api.insights import InsightsResponse, RecommendationCard, get_insights
from app.db.plans import AuthenticatedUser
from app.recommendations import apply_policy, build_contextual_recommendations, dedup_key
from app.services.weather import HourlyForecast
from test_insights import FakeInsightsStore, FIXED_NOW


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


def test_contextual_candidates_use_only_supplied_context():
    assert build_contextual_recommendations(
        profile={}, plans=[], now=FIXED_NOW, timezone_name="Europe/Istanbul"
    ) == []


def test_contextual_candidates_include_entered_deadline_availability_and_upcoming_plan():
    next_day = (FIXED_NOW.date() + timedelta(days=2)).isoformat()
    plan = {
        "id": "plan-1", "title": "Biology study", "planned_start": (FIXED_NOW + timedelta(days=1)).isoformat(),
        "latest_outcome": None,
    }
    cards = build_contextual_recommendations(
        profile={
            "deadlines_goals": [{"title": "Biology exam", "kind": "exam", "deadline": next_day}],
            "typical_availability": ["Tuesday afternoons"],
        },
        plans=[plan], now=FIXED_NOW, timezone_name="Europe/Istanbul",
    )
    assert {card["source"] for card in cards} == {"contextual"}
    assert any("Biology exam" in card["evidence"].values() for card in cards)
    assert any(card["evidence"].get("plan_id") == "plan-1" for card in cards)
    assert any(card["evidence"].get("typical_availability") == "Tuesday afternoons" for card in cards)
    assert all(card["label"] and card["why"] for card in cards)
    schema = json.loads((Path(__file__).resolve().parents[2] / "ai" / "schema.json").read_text())
    selected = apply_policy([], [], contextual=cards, now=FIXED_NOW)[0]
    parsed = RecommendationCard.model_validate(selected).model_dump(mode="json")
    validate(instance=parsed, schema=schema["$defs"]["RecommendationCard"])


def test_contextual_weather_card_uses_forecast_and_discloses_default_area():
    plan = {
        "id": "plan-2", "title": "Outdoor run", "planned_start": (FIXED_NOW + timedelta(hours=2)).isoformat(),
        "latest_outcome": None,
    }
    forecast = HourlyForecast(FIXED_NOW + timedelta(hours=2), 80, 61, True)
    cards = build_contextual_recommendations(
        profile={}, plans=[plan], now=FIXED_NOW, timezone_name="Europe/Istanbul", weather_forecast=forecast,
    )
    weather = next(card for card in cards if card["id"] == "context-weather-plan-2")
    assert weather["evidence"]["precipitation_probability"] == 80
    assert "not a saved user location" in weather["evidence"]["forecast_area"]
    assert weather["label"] == "Weather context · app default location"


def test_expired_profile_deadlines_do_not_generate_context():
    cards = build_contextual_recommendations(
        profile={"deadlines_goals": [{"title": "Old exam", "kind": "exam", "deadline": "2026-01-01"}]},
        plans=[], now=FIXED_NOW, timezone_name="Europe/Istanbul",
    )
    assert cards == []


def test_policy_balances_sources_caps_cards_and_honors_context_dismissal(monkeypatch):
    monkeypatch.setenv("RECOMMENDATION_BEHAVIOR_SLOTS", "1")
    monkeypatch.setenv("RECOMMENDATION_CONTEXTUAL_SLOTS", "1")
    contextual = [{
        "id": "context-goal-1", "title": "Entered exam", "message": "Review it.", "why": "Based on the date you entered.",
        "evidence": {"deadline": "2026-10-28"}, "confidence": "moderate", "next_step": "Review it.",
        "source": "contextual", "label": "Based on the exam date you entered",
    }]
    cards = apply_policy([], [], contextual=contextual, now=FIXED_NOW)
    assert len(cards) == 3
    assert cards[0]["source"] == "contextual"
    assert len({card["dedup_key"] for card in cards}) == len(cards)
    dismissed = apply_policy(
        [], [{"recommendation_id": "context-goal-1", "action": "dismissed", "created_at": FIXED_NOW.isoformat()}],
        contextual=contextual, now=FIXED_NOW,
    )
    assert "context-goal-1" not in [card["id"] for card in dismissed]
    InsightsResponse.model_validate({"recommendations": cards, "period": "all", "planned": 0, "done": 0,
        "postponed": 0, "skipped": 0, "unreported": 0, "adherence_pct": None, "avg_start_delay_min": None,
        "by_weekday": {}, "by_hour": {}, "by_category": {}, "postponed_targets": [], "trend_vs_prev": None,
        "narrative": None, "is_demo": False, "data_label": "real"})


def test_insights_contextual_card_is_user_profile_scoped_and_frequency_off_suppresses_it(monkeypatch):
    store = FakeInsightsStore()
    user = AuthenticatedUser("user-context", "Europe/Istanbul", False, None)
    store.add_plan(user_id=user.id, title="Study session", start=FIXED_NOW + timedelta(days=1))
    store.personalization[user.id] = {
        "deadlines_goals": [{"title": "Exam", "kind": "exam", "deadline": (FIXED_NOW.date() + timedelta(days=3)).isoformat()}],
        "typical_availability": [],
    }
    monkeypatch.setattr("app.api.insights.WeatherService.get_forecast", lambda *args, **kwargs: None)
    result = get_insights(user=user, store=store, period="all", current_time=FIXED_NOW)
    InsightsResponse.model_validate(result)
    assert any(card["source"] == "contextual" for card in result["recommendations"])
    assert any(card["label"] == "Based on the exam date you entered" for card in result["recommendations"])

    store.personalization[user.id]["recommendation_frequency"] = "off"
    def unexpected_weather_call(*args, **kwargs):
        raise AssertionError("weather must not be queried when recommendations are off")
    monkeypatch.setattr("app.api.insights.WeatherService.get_forecast", unexpected_weather_call)
    suppressed = get_insights(user=user, store=store, period="all", current_time=FIXED_NOW)
    assert suppressed["recommendations"] == []

