"""Speech sanitizer to normalize text before sending to TTS.

Ensures speech is 100% natural and free of non-word characters, symbols,
and raw digits that cause speech synthesis engines to distort or mispronounce.
All numbers (times, dates, durations, button IDs) are converted to English words.
"""

from __future__ import annotations

import re

_ONES = {
    0: "zero",
    1: "one",
    2: "two",
    3: "three",
    4: "four",
    5: "five",
    6: "six",
    7: "seven",
    8: "eight",
    9: "nine",
    10: "ten",
    11: "eleven",
    12: "twelve",
    13: "thirteen",
    14: "fourteen",
    15: "fifteen",
    16: "sixteen",
    17: "seventeen",
    18: "eighteen",
    19: "nineteen",
}

_TENS = {
    20: "twenty",
    30: "thirty",
    40: "forty",
    50: "fifty",
    60: "sixty",
    70: "seventy",
    80: "eighty",
    90: "ninety",
}

_ORDINALS_UNDER_20 = {
    1: "first",
    2: "second",
    3: "third",
    4: "fourth",
    5: "fifth",
    6: "sixth",
    7: "seventh",
    8: "eighth",
    9: "ninth",
    10: "tenth",
    11: "eleventh",
    12: "twelfth",
    13: "thirteenth",
    14: "fourteenth",
    15: "fifteenth",
    16: "sixteenth",
    17: "seventeenth",
    18: "eighteenth",
    19: "nineteenth",
}

_MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

_CONTRACTIONS: list[tuple[str, str]] = [
    (r"\bI've\b", "I have"),
    (r"\bI'm\b", "I am"),
    (r"\bI'll\b", "I will"),
    (r"\bwe'll\b", "we will"),
    (r"\byou'll\b", "you will"),
    (r"\bthey'll\b", "they will"),
    (r"\bdon't\b", "do not"),
    (r"\bdoesn't\b", "does not"),
    (r"\bdidn't\b", "did not"),
    (r"\bcan't\b", "cannot"),
    (r"\bwon't\b", "will not"),
    (r"\bit's\b", "it is"),
    (r"\bthat's\b", "that is"),
    (r"\blet's\b", "let us"),
    (r"\bthere's\b", "there is"),
    (r"\baren't\b", "are not"),
    (r"\bisn't\b", "is not"),
    (r"\bwasn't\b", "was not"),
    (r"\bweren't\b", "were not"),
    (r"\bhaven't\b", "have not"),
    (r"\bhasn't\b", "has not"),
    (r"\bhadn't\b", "had not"),
]


def int_to_words(n: int) -> str:
    """Converts an integer to English words (e.g. 45 -> forty five)."""
    if n < 0:
        return f"minus {int_to_words(-n)}"
    if n < 20:
        return _ONES.get(n, str(n))
    if n < 100:
        ten, rem = divmod(n, 10)
        base = _TENS.get(ten * 10, f"{ten}0")
        return base if rem == 0 else f"{base} {_ONES[rem]}"
    if n < 1000:
        hundred, rem = divmod(n, 100)
        base = f"{_ONES[hundred]} hundred"
        return base if rem == 0 else f"{base} {int_to_words(rem)}"
    if 2000 <= n <= 2099:
        rem = n % 100
        return "twenty hundred" if rem == 0 else f"twenty {int_to_words(rem)}"
    thousand, rem = divmod(n, 1000)
    base = f"{int_to_words(thousand)} thousand"
    return base if rem == 0 else f"{base} {int_to_words(rem)}"


def int_to_ordinal(n: int) -> str:
    """Converts an integer to ordinal English words (e.g. 26 -> twenty sixth)."""
    if n in _ORDINALS_UNDER_20:
        return _ORDINALS_UNDER_20[n]
    if n % 10 == 0 and n < 100:
        tens_ord = {
            20: "twentieth",
            30: "thirtieth",
            40: "fortieth",
            50: "fiftieth",
            60: "sixtieth",
            70: "seventieth",
            80: "eightieth",
            90: "ninetieth",
        }
        return tens_ord.get(n, f"{int_to_words(n)}th")
    if n < 100:
        ten, rem = divmod(n, 10)
        base = _TENS.get(ten * 10, "")
        ord_rem = _ORDINALS_UNDER_20.get(rem, _ONES.get(rem, "") + "th")
        return f"{base} {ord_rem}"
    return f"{int_to_words(n)}th"


def _replace_iso_date(match: re.Match[str]) -> str:
    try:
        m = int(match.group(2))
        d = int(match.group(3))
        if 1 <= m <= 12 and 1 <= d <= 31:
            month_name = _MONTHS[m - 1]
            return f"{month_name} {int_to_ordinal(d)}"
    except Exception:
        pass
    return match.group(0)


def _replace_time_24(match: re.Match[str]) -> str:
    try:
        h = int(match.group(1))
        m = int(match.group(2))
        if 0 <= h <= 23 and 0 <= m <= 59:
            if h == 0 and m == 0:
                return "midnight"
            if h == 12 and m == 0:
                return "noon"
            ampm = "AM" if h < 12 else "PM"
            disp_h = h % 12 or 12
            h_word = int_to_words(disp_h)
            if m == 0:
                return f"{h_word} {ampm}"
            m_word = int_to_words(m)
            return f"{h_word} {m_word} {ampm}"
    except Exception:
        pass
    return match.group(0)


def _replace_time_ampm(match: re.Match[str]) -> str:
    try:
        h = int(match.group(1))
        ampm = match.group(2).upper()
        return f"{int_to_words(h)} {ampm}"
    except Exception:
        return match.group(0)


def _replace_ordinal_str(match: re.Match[str]) -> str:
    try:
        val = int(match.group(1))
        return int_to_ordinal(val)
    except Exception:
        return match.group(0)


def sanitize_for_speech(text: str) -> str:
    """Cleans and normalizes text for speech synthesis so speech does not get distorted.

    - Replaces all numbers and digits with spelled-out English words.
    - Expands contractions.
    - Strips all non-word symbols except letters, spaces, and pause punctuation (., ?).
    """
    if not text:
        return ""

    # 1. Expand contractions (e.g. I've -> I have, don't -> do not)
    for pattern, repl in _CONTRACTIONS:
        text = re.sub(pattern, repl, text, flags=re.IGNORECASE)

    # 2. Convert ISO dates YYYY-MM-DD -> e.g. "October twenty sixth"
    text = re.sub(r"\b(\d{4})-(\d{2})-(\d{2})\b", _replace_iso_date, text)

    # 3. Convert ordinals (e.g. 26th, 1st, 2nd, 3rd) -> words
    text = re.sub(r"\b(\d+)(?:st|nd|rd|th)\b", _replace_ordinal_str, text, flags=re.IGNORECASE)

    # 4. Convert 24-hr times HH:MM -> e.g. "eight AM" or "six thirty PM"
    text = re.sub(r"\b(\d{1,2}):(\d{2})\b", _replace_time_24, text)

    # 5. Convert times with AM/PM like "8 AM", "6 PM"
    text = re.sub(r"\b(\d{1,2})\s*(AM|PM|am|pm)\b", _replace_time_ampm, text)

    # 6. Replace ranges like "30-45" with "thirty to forty five"
    text = re.sub(
        r"(\d+)\s*[-–—]\s*(\d+)",
        lambda m: f"{int_to_words(int(m.group(1)))} to {int_to_words(int(m.group(2)))}",
        text,
    )

    # 7. Convert ANY remaining standalone numbers to words (e.g. "button 1" -> "button one", "45" -> "forty five")
    text = re.sub(r"\b(\d+)\b", lambda m: int_to_words(int(m.group(1))), text)

    # 8. Replace hyphens, dashes, colons, slashes with spaces
    text = re.sub(r"[-–—/:]+", " ", text)

    # 9. Strip ALL remaining non-word characters (keep letters, unicode word characters, spaces, and pause punctuation: ., ?)
    text = re.sub(r"[^\w\s.,?]", " ", text)

    # 10. Collapse duplicate punctuation and spaces
    text = re.sub(r"\s*([.,?])\s*", r"\1 ", text)
    text = re.sub(r"\s+", " ", text).strip()

    return text
