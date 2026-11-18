"""
Deterministic evaluators (no LLM judge): fast, free, repeatable.

LangSmith calls each one with (inputs, outputs, reference_outputs) and records the returned
{"key", "score", "comment"}. A score of None means "not applicable for this case".
"""

import re

# ------------------------------------------------------------ extraction ----


def correct_type(outputs: dict, reference_outputs: dict) -> dict:
    want, got = reference_outputs.get("destination_type"), outputs.get("destination_type")
    return {"key": "correct_type", "score": int(got == want), "comment": f"expected {want}, got {got}"}


def correct_destination_airport(outputs: dict, reference_outputs: dict) -> dict:
    if "to_iata" not in reference_outputs:
        return {"key": "correct_airport", "score": None, "comment": "not checked"}
    want, got = reference_outputs["to_iata"], outputs.get("to_iata")
    ok = (got is None) if want is None else (got in want)
    return {"key": "correct_airport", "score": int(ok), "comment": f"expected {want}, got {got}"}


def correct_origin(outputs: dict, reference_outputs: dict) -> dict:
    if "from_iata" not in reference_outputs:
        return {"key": "correct_origin", "score": None, "comment": "not checked"}
    want, got = reference_outputs["from_iata"], outputs.get("from_iata")
    return {"key": "correct_origin", "score": int(got in want), "comment": f"expected {want}, got {got}"}


def correct_days(outputs: dict, reference_outputs: dict) -> dict:
    if "trip_days" not in reference_outputs:
        return {"key": "correct_days", "score": None, "comment": "not checked"}
    want, got = reference_outputs["trip_days"], outputs.get("trip_days")
    return {"key": "correct_days", "score": int(got == want), "comment": f"expected {want}, got {got}"}


def correct_date(outputs: dict, reference_outputs: dict) -> dict:
    if "departure_date" not in reference_outputs:
        return {"key": "correct_date", "score": None, "comment": "not checked"}
    want, got = reference_outputs["departure_date"], outputs.get("departure_date")
    return {"key": "correct_date", "score": int(got == want), "comment": f"expected {want}, got {got}"}


EXTRACTION_EVALUATORS = [correct_type, correct_destination_airport, correct_origin, correct_days, correct_date]


# -------------------------------------------------------------- full run ----

# Currency markers that may appear in an itinerary, and which countries they belong to.
_CURRENCY_PATTERNS = {
    "GBP": r"£|\bGBP\b",
    "EUR": r"€|\bEUR\b",
    "INR": r"₹|\bINR\b|\bRs\.?\s?\d",
    "USD": r"(?<![A-Z])\$|\bUS\$|\bUSD\b",
    "CAD": r"\bC\$|\bCAD\b",
    "TRY": r"\bTL\s?\d|\bTRY\b",
    "JPY": r"¥|\bJPY\b",
}
_LOCAL_CURRENCY = {
    "GB": "GBP", "IN": "INR", "FR": "EUR", "IT": "EUR", "ES": "EUR", "DE": "EUR", "PT": "EUR",
    "IE": "EUR", "NL": "EUR", "GR": "EUR", "US": "USD", "JP": "JPY", "CA": "CAD", "TR": "TRY",
}


def routed_correctly(outputs: dict, reference_outputs: dict) -> dict:
    return correct_type(outputs, reference_outputs) | {"key": "routed_correctly"}


def day_count_matches(outputs: dict, reference_outputs: dict) -> dict:
    """Number of distinct 'Day N' headings equals the requested trip length."""
    text = outputs.get("itinerary") or ""
    days = {int(n) for n in re.findall(r"\bDay\s+(\d{1,2})\b", text, flags=re.IGNORECASE)}
    want = reference_outputs.get("trip_days") or outputs.get("trip_days")
    return {"key": "day_count_matches", "score": int(len(days) == want),
            "comment": f"expected {want} days, found {sorted(days)}"}


def stays_in_destination(outputs: dict, reference_outputs: dict) -> dict:
    """The itinerary names the destination (or a planned stop) rather than the departure city."""
    text = (outputs.get("itinerary") or "").lower()
    names = [outputs.get("destination_name") or ""] + [s.get("name", "") for s in outputs.get("plan_stops") or []]
    words = {n.split(",")[0].strip().lower() for n in names if n}
    hit = [w for w in words if w and w in text]
    return {"key": "stays_in_destination", "score": int(bool(hit)), "comment": f"looked for {sorted(words)}, found {hit}"}


def no_invented_booking(outputs: dict, reference_outputs: dict) -> dict:
    """The planner must never claim that something is already booked."""
    text = (outputs.get("itinerary") or "").lower()
    bad = re.findall(r"already booked|you have booked|your booked|booking confirmed|reservation confirmed", text)
    return {"key": "no_invented_booking", "score": int(not bad), "comment": ", ".join(bad) or "none"}


def local_currency_only(outputs: dict, reference_outputs: dict) -> dict:
    """Prices use the destination's currency (GBP is also allowed, as the user is UK-based)."""
    country = reference_outputs.get("country")
    local = _LOCAL_CURRENCY.get(country or "")
    if not local:
        return {"key": "local_currency_only", "score": None, "comment": f"no currency rule for {country}"}
    text = outputs.get("itinerary") or ""
    found = {cur for cur, pat in _CURRENCY_PATTERNS.items() if re.search(pat, text)}
    foreign = found - {local, "GBP"}
    return {"key": "local_currency_only", "score": int(not foreign),
            "comment": f"allowed {local}/GBP, found {sorted(found) or 'none'}"}


def under_time_budget(outputs: dict, reference_outputs: dict, budget_s: float = 180.0) -> dict:
    secs = outputs.get("seconds")
    if secs is None:
        return {"key": "under_180s", "score": None, "comment": "no timing"}
    return {"key": "under_180s", "score": int(secs <= budget_s), "comment": f"{secs:.0f}s"}


FULL_EVALUATORS = [routed_correctly, day_count_matches, stays_in_destination,
                   no_invented_booking, local_currency_only, under_time_budget]
