"""Immediate deterministic greeting detection and response generation.

Provides instant (<1ms) greeting responses for GAP-AI Plan Mode and Coach Mode
without calling remote LLMs, while ensuring greetings followed by actionable requests
continue into their respective planning or recommendation flows.
"""

from __future__ import annotations

import re
from typing import Literal

# English greeting tokens
_EN_GREETING_TOKENS = {
    "hi",
    "hello",
    "hey",
    "howdy",
    "greetings",
    "good morning",
    "good afternoon",
    "good evening",
    "hi there",
    "hello there",
    "hey there",
}

# Turkish greeting tokens
_TR_GREETING_TOKENS = {
    "merhaba",
    "selam",
    "selamlar",
    "gunaydin",
    "günaydın",
    "iyi gunler",
    "iyi günler",
    "iyi aksamlar",
    "iyi akşamlar",
    "tunaydin",
    "tünaydın",
    "hey",
}

# Addressee tokens that can accompany greetings
_ADDRESS_TOKENS = {
    "coach",
    "assistant",
    "gap",
    "gap ai",
    "coach ai",
    "koc",
    "koç",
    "asistan",
    "ai",
}

# Actionable trigger words indicating the utterance contains a real request
_ACTIONABLE_TRIGGERS = {
    "plan",
    "create",
    "schedule",
    "walk",
    "run",
    "study",
    "work",
    "gym",
    "meeting",
    "read",
    "cook",
    "eat",
    "dinner",
    "lunch",
    "breakfast",
    "tomorrow",
    "today",
    "tonight",
    "yesterday",
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
    "at",
    "pm",
    "am",
    "recommend",
    "recommendation",
    "idea",
    "suggest",
    "suggestion",
    "what",
    "how",
    "weather",
    "check",
    "show",
    "tell",
    "give",
    "can you",
    "could you",
    "i want",
    "i need",
    "let",
    "lets",
    "let's",
    "yap",
    "planla",
    "olustur",
    "oluştur",
    "yuruyus",
    "yürüyüş",
    "kosu",
    "koşu",
    "ders",
    "toplanti",
    "toplantı",
    "oneri",
    "öneri",
    "fikir",
    "tavsiye",
    "hava",
    "durumu",
    "nasil",
    "nasıl",
    "bugun",
    "bugün",
    "yarin",
    "yarın",
    "aksam",
    "akşam",
    "sabah",
    "saat",
}

# Fixed deterministic phrases
GREETING_RESPONSES = {
    "coach": {
        "en": "Hi! How can I help you today?",
        "tr": "Merhaba! Bugün senin için ne yapabilirim?",
    },
    "plan": {
        "en": "Hi! Would you like to create a plan?",
        "tr": "Merhaba! Yeni bir plan oluşturalım mı?",
    },
}


def _normalize_text(text: str) -> str:
    """Normalize text by lowering, removing punctuation, and normalizing whitespace."""
    lower = text.lower().strip()
    # Normalize Turkish specific characters for matching flexibility
    cleaned = re.sub(r"[^\w\s]", " ", lower)
    tokens = [t for t in cleaned.split() if t]
    return " ".join(tokens)


def check_standalone_greeting(
    text: str,
    default_language: str | None = None,
) -> tuple[bool, Literal["en", "tr"]]:
    """Determines whether utterance is a standalone greeting without actionable requests.

    Returns:
        (is_greeting, detected_language)
    """
    norm = _normalize_text(text)
    if not norm:
        return False, "en"

    tokens = norm.split()

    # 1. Check for actionable trigger words
    for token in tokens:
        if token in _ACTIONABLE_TRIGGERS:
            return False, "en"

    # Also check two-word triggers (e.g. "can you", "i want", "let's")
    for i in range(len(tokens) - 1):
        bigram = f"{tokens[i]} {tokens[i+1]}"
        if bigram in _ACTIONABLE_TRIGGERS:
            return False, "en"

    # 2. Strip known addressee tokens from the token list
    filtered_tokens = [t for t in tokens if t not in _ADDRESS_TOKENS]
    if not filtered_tokens:
        # If user only said "Coach" or "GAP", that is an address, not a greeting
        return False, "en"

    filtered_norm = " ".join(filtered_tokens)

    # 3. Disambiguate language
    # Check English greetings first unless specifically Turkish tokens are present
    has_tr_specific = any(
        t in {"merhaba", "selam", "selamlar", "gunaydin", "günaydın", "iyi", "günler", "gunler", "aksamlar", "akşamlar", "koc", "koç", "tunaydin", "tünaydın"}
        for t in tokens
    )

    if has_tr_specific:
        if filtered_norm in _TR_GREETING_TOKENS or all(t in _TR_GREETING_TOKENS for t in filtered_tokens):
            return True, "tr"
        for g in _TR_GREETING_TOKENS:
            if norm == g:
                return True, "tr"
            for a in _ADDRESS_TOKENS:
                if norm in (f"{g} {a}", f"{a} {g}"):
                    return True, "tr"

    # Check English greetings
    if filtered_norm in _EN_GREETING_TOKENS or all(t in _EN_GREETING_TOKENS for t in filtered_tokens):
        return True, "en"

    for g in _EN_GREETING_TOKENS:
        if norm == g:
            return True, "en"
        for a in _ADDRESS_TOKENS:
            if norm in (f"{g} {a}", f"{a} {g}"):
                return True, "en"

    # Fallback to Turkish if matches
    if filtered_norm in _TR_GREETING_TOKENS or all(t in _TR_GREETING_TOKENS for t in filtered_tokens):
        return True, "tr"

    return False, "en"


def is_standalone_greeting(text: str) -> bool:
    """Returns True if the utterance is a standalone greeting without actionable requests."""
    is_greet, _ = check_standalone_greeting(text)
    return is_greet


def get_deterministic_greeting(
    mode: Literal["plan", "coach"] = "plan",
    language: Literal["en", "tr"] = "en",
) -> str:
    """Returns the mode-dependent, language-appropriate deterministic greeting text."""
    mode_key = "coach" if mode == "coach" else "plan"
    lang_key = "tr" if language == "tr" else "en"
    return GREETING_RESPONSES[mode_key][lang_key]


def get_deterministic_greeting_for_text(
    text: str,
    mode: Literal["plan", "coach"] = "plan",
) -> tuple[str, Literal["en", "tr"]]:
    """Inspects text for greeting language and returns (greeting_reply_text, detected_language)."""
    _, lang = check_standalone_greeting(text)
    reply = get_deterministic_greeting(mode=mode, language=lang)
    return reply, lang
