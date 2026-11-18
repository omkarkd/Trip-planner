"""
OAG Flight Info API (v2) helpers.

    from travel_agent.tools import flight_tool
    print(flight_tool("LGW", "BOM", "2026-11-25"))

Requires OAG_FLIGHT_API_KEY in .env.
"""

import logging
from datetime import date

import requests

from .. import config
from .cache import cached
from .geo import alternative_origins, is_valid_iata

log = logging.getLogger("travel_agent.flights")

_OAG_URL = f"{config.OAG_BASE_URL}/flight-instances/"


@cached(ttl_seconds=config.FLIGHT_CACHE_TTL, cache_if=lambda r: isinstance(r, dict) and not r.get("error"))
def search_oag(from_iata: str, to_iata: str, dep_date: str, limit: int = 10) -> dict:
    """Raw OAG response for direct flights on one route and date. Never raises: errors go in 'error'."""
    if not config.OAG_FLIGHT_API_KEY:
        return {"data": [], "error": "OAG_FLIGHT_API_KEY is not set"}

    params = {
        "DepartureAirport": from_iata.upper(),
        "ArrivalAirport": to_iata.upper(),
        "DepartureDateTime": dep_date,
        "CodeType": "IATA",
        "Limit": limit,
        "version": "v2",
    }
    try:
        r = requests.get(
            _OAG_URL,
            params=params,
            headers={"Subscription-Key": config.OAG_FLIGHT_API_KEY},
            timeout=30,
        )
    except requests.RequestException as exc:
        log.warning("OAG request failed %s->%s: %s", from_iata, to_iata, exc)
        return {"data": [], "error": str(exc)}

    log.info("OAG %s -> %s on %s: HTTP %s", from_iata, to_iata, dep_date, r.status_code)
    if r.status_code != 200:
        return {"data": [], "error": f"HTTP {r.status_code}: {r.text[:200]}"}
    return r.json()


def format_oag_flights(data: dict, max_rows: int = 10) -> str:
    """Turn an OAG response into short lines for the LLM. Missing fields become '?'."""
    flights = (data or {}).get("data") or []
    if not flights:
        return "No direct flights found."

    def leg(x: dict) -> str:
        airport = (x.get("airport") or {}).get("iata", "?")
        d = (x.get("date") or {}).get("local", "")
        t = (x.get("time") or {}).get("local", "")
        return f"{airport} {d} {t}".strip()

    lines = []
    for f in flights[:max_rows]:
        dep = f.get("departure") or {}
        arr = f.get("arrival") or {}
        carrier = (f.get("carrier") or {}).get("iata", "?")
        aircraft = f.get("aircraftType") or {}
        aircraft_code = aircraft.get("icao") or aircraft.get("iata") or "?"
        stops = (f.get("segmentInfo") or {}).get("numberOfStops", "?")
        mins = f.get("elapsedTime") or 0
        lines.append(
            f"{carrier}{f.get('flightNumber', '')} | {leg(dep)} -> {leg(arr)} | "
            f"{mins // 60}h{mins % 60:02d}m | {stops} stop(s) | aircraft {aircraft_code}"
        )
    return "\n".join(lines)


def flight_tool(from_iata: str, to_iata: str, dep_date: str) -> str:
    """
    Direct flights from an origin (and the other airports in its metro area) to a destination.
    Returns formatted text for the itinerary prompt.
    """
    if not is_valid_iata(from_iata):
        return f"Unknown departure airport code: {from_iata!r}."
    if not is_valid_iata(to_iata):
        return f"Unknown destination airport code: {to_iata!r}."
    try:
        date.fromisoformat(dep_date)
    except (TypeError, ValueError):
        return f"Invalid departure date {dep_date!r}; expected YYYY-MM-DD."

    last_error = None
    for origin in alternative_origins(from_iata):
        data = search_oag(origin, to_iata, dep_date)
        if data.get("data"):
            return format_oag_flights(data)
        last_error = data.get("error") or last_error

    if last_error:
        return f"Flight search failed ({last_error}). No flight data available."
    return f"No direct flights found from {from_iata} (or nearby airports) to {to_iata} on {dep_date}."
