"""Short spoken reply for the device, built deterministically from a ParsedPlan.

No extra LLM call: the reply only restates what Nemotron already extracted, so it
is fast, free and cannot invent details.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

_TR_MONTHS = (
    "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
    "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık",
)
_EN_MONTHS = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)


def _spoken_day(plan_date: str | None, today: str | None, language: str) -> str | None:
    try:
        target = date.fromisoformat(str(plan_date))
    except ValueError:
        return None
    try:
        ref = date.fromisoformat(str(today)) if today else None
    except ValueError:
        ref = None

    if ref is not None and target == ref:
        return "bugün" if language == "tr" else "today"
    if ref is not None and target == ref + timedelta(days=1):
        return "yarın" if language == "tr" else "tomorrow"
    if language == "tr":
        return f"{target.day} {_TR_MONTHS[target.month - 1]}"
    return f"{_EN_MONTHS[target.month - 1]} {target.day}"


def build_reply_text(parsed_plan: dict[str, Any], today: str | None = None) -> str:
    """Returns one or two sentences the device can say back to the user."""
    language = "en" if parsed_plan.get("language") == "en" else "tr"
    intent = parsed_plan.get("intent")

    if intent == "create_plan":
        title = str(parsed_plan.get("title") or ("plan" if language == "en" else "Plan"))
        day = _spoken_day(parsed_plan.get("date"), today, language)
        time = parsed_plan.get("time")
        if language == "en":
            when = " ".join(part for part in (day, f"at {time}" if time else None) if part)
            return f"Okay, I saved {title} for {when}." if when else f"Okay, I saved {title}."
        when = " ".join(part for part in (day, f"saat {time}" if time else None) if part)
        return f"Tamam, {title} planını {when} için kaydettim." if when else f"Tamam, {title} planını kaydettim."

    if intent == "clarify":
        question = parsed_plan.get("clarification_question")
        if isinstance(question, str) and question.strip():
            return question.strip()
        return "Can you give me a bit more detail?" if language == "en" else "Biraz daha detay verir misin?"

    if language == "en":
        return "Sorry, I couldn't turn that into a plan. Try something like: run tomorrow at 6 pm."
    return "Bunu bir plana çeviremedim. Örneğin: yarın akşam 6'da koşu, diyebilirsin."
