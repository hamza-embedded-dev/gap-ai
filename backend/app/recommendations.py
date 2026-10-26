"""Deterministic recommendation policy and neutral discovery catalog."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import os
from typing import Any

DISMISSAL_DAYS = 30

DISCOVERY_IDEAS = [
    {"id": "discovery-walk", "title": "Take a short walk", "message": "Try a 15-minute walk as a small reset.", "duration_minutes": 15},
    {"id": "discovery-learn", "title": "Learn one small thing", "message": "Spend 20 minutes exploring a topic you choose.", "duration_minutes": 20},
    {"id": "discovery-project", "title": "Make a tiny project", "message": "Choose a simple idea and build its first small piece.", "duration_minutes": 30},
    {"id": "discovery-break", "title": "Take a healthy break", "message": "Step away for 10 minutes, stretch, and rest your eyes.", "duration_minutes": 10},
    {"id": "discovery-experience", "title": "Try a nearby experience", "message": "Pick a place or activity you have not tried before.", "duration_minutes": 45},
]


def dedup_key(item: dict[str, Any]) -> str:
    """Stable SHA-256 of normalized idea identity; excludes message wording and duration."""
    identity = f"{item.get('source', 'discovery')}:{item.get('id', '')}".strip().lower()
    return hashlib.sha256(identity.encode()).hexdigest()


def apply_policy(behavior: list[dict[str, Any]], feedback: list[dict[str, Any]], *, now: datetime | None = None) -> list[dict[str, Any]]:
    now = now or datetime.now(timezone.utc)
    try:
        behavior_slots = max(0, min(3, int(os.getenv("RECOMMENDATION_BEHAVIOR_SLOTS", "2"))))
    except ValueError:
        behavior_slots = 2
    discovery_slots = 3 - behavior_slots
    hidden: set[str] = set()
    expired_dismissals: set[str] = set()
    useful = set()
    not_useful = set()
    for entry in feedback:
        rid = entry.get("recommendation_id")
        if entry.get("action") == "dismissed":
            try:
                created = datetime.fromisoformat(str(entry["created_at"]).replace("Z", "+00:00"))
            except (KeyError, ValueError):
                continue
            if created > now - timedelta(days=DISMISSAL_DAYS):
                hidden.add(rid)
            else:
                expired_dismissals.add(rid)
        if entry.get("rating") == "useful":
            useful.add(rid)
        elif entry.get("rating") == "not_useful":
            not_useful.add(rid)
    behavior = [dict(r, source="behavior", label=None) for r in behavior if r["id"] not in hidden]
    discovery = [dict(i, source="discovery", label="Not based on your history", why="Starter idea; not based on your history.", confidence="none", evidence={}, next_step=i["message"]) for i in DISCOVERY_IDEAS if i["id"] not in hidden]
    # Persisted useful feedback affects selection: positively rated ideas are prioritized.
    rank = lambda r: (r["id"] not in useful, r["id"] not in expired_dismissals, r["id"] in not_useful, r["id"])
    behavior.sort(key=rank)
    discovery.sort(key=rank)
    chosen = behavior[:behavior_slots]
    chosen.extend(discovery[:discovery_slots])
    # Fill unused slots from either pool while preserving the default balance when possible.
    used = {item["id"] for item in chosen}
    chosen.extend([r for r in behavior + discovery if r["id"] not in used][:3-len(chosen)])
    for item in chosen:
        item["dedup_key"] = dedup_key(item)
    return chosen[:3]
