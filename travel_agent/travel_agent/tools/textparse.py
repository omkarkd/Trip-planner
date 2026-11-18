"""
Rule-based fallbacks for details small models often miss: dates and the departure place.
Used only when the LLM returns nothing valid for that field.
"""

import re
from datetime import date

from .. import config
from .geo import country_code_of_airport, find_airport_for_city, is_country, is_valid_iata

_MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july",
     "august", "september", "october", "november", "december"], start=1)}
_MONTHS.update({name[:3]: num for name, num in list(_MONTHS.items())})
_MONTHS["sept"] = 9
_MONTH_RE = "|".join(sorted(_MONTHS, key=len, reverse=True))

_COUNTRY_ALIASES = {"uk": "GB", "u.k.": "GB", "britain": "GB", "england": "GB", "scotland": "GB",
                    "wales": "GB", "united kingdom": "GB"}


def _safe_date(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def _future(m: int, d: int, today: date) -> date | None:
    """A day/month with no year: this year if still ahead, otherwise next year."""
    candidate = _safe_date(today.year, m, d)
    if candidate and candidate < today:
        candidate = _safe_date(today.year + 1, m, d)
    return candidate


def find_date_in_text(text: str, today: date | None = None) -> str | None:
    """First date mentioned in the text, as YYYY-MM-DD. UK order for 20/12/2026."""
    today = today or date.today()
    t = text.lower()

    if m := re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", t):                       # 2026-12-20
        found = _safe_date(int(m[1]), int(m[2]), int(m[3]))
        return found.isoformat() if found else None

    if m := re.search(r"\b(\d{1,2})[/.](\d{1,2})[/.](\d{2,4})\b", t):                # 20/12/2026
        year = int(m[3]) + (2000 if len(m[3]) == 2 else 0)
        found = _safe_date(year, int(m[2]), int(m[1]))
        return found.isoformat() if found else None

    if m := re.search(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({_MONTH_RE})\.?(?:\s+(\d{{4}}))?\b", t):  # 20 December
        month, day = _MONTHS[m[2]], int(m[1])
        found = _safe_date(int(m[3]), month, day) if m[3] else _future(month, day, today)
        return found.isoformat() if found else None

    if m := re.search(rf"\b({_MONTH_RE})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(\d{{4}}))?\b", t):  # December 20
        month, day = _MONTHS[m[1]], int(m[2])
        found = _safe_date(int(m[3]), month, day) if m[3] else _future(month, day, today)
        return found.isoformat() if found else None

    return None


def _resolve_origin(place: str) -> str | None:
    place = place.strip(" .,'").lower()
    if not place:
        return None
    if len(place) == 3 and is_valid_iata(place):
        return place.upper()
    home_cc = country_code_of_airport(config.DEFAULT_ORIGIN)
    cc = _COUNTRY_ALIASES.get(place)
    if cc or is_country(place):
        # "from the UK" -> default origin, if it is in that country
        return config.DEFAULT_ORIGIN if (cc or "").upper() == home_cc else None
    return find_airport_for_city(place)


def find_origin_in_text(text: str) -> str | None:
    """Departure airport from 'from X ...' or 'X to Y' phrasing; None if not recognisable."""
    t = text.lower().strip()
    patterns = [
        r"\bfrom\s+([a-z][a-z .'\-]{1,30}?)\s+(?:to|for|on|in|into|towards)\b",
        r"\bfrom\s+([a-z][a-z .'\-]{1,30}?)\s*$",
        r"^(?:fly(?:ing)?\s+)?([a-z][a-z .'\-]{1,30}?)\s+to\s+",
    ]
    for pat in patterns:
        if m := re.search(pat, t):
            code = _resolve_origin(m[1])
            if code:
                return code
    return None
