"""
Deterministic geography helpers: airports, countries, seasons, day allocation.
No LLM calls here, so these are fast and reliable checks on LLM output.

Requires:  uv add airportsdata pycountry
"""

import calendar
from functools import lru_cache

import airportsdata
import pycountry

# Airports in the same metro area, tried as fallback origins when the first has no flights.
METRO_AIRPORTS: dict[str, list[str]] = {
    "LON": ["LHR", "LGW", "STN", "LTN", "LCY", "SEN"],
    "NYC": ["JFK", "EWR", "LGA"],
    "PAR": ["CDG", "ORY"],
    "TYO": ["HND", "NRT"],
    "MIL": ["MXP", "LIN", "BGY"],
    "ROM": ["FCO", "CIA"],
    "BJS": ["PEK", "PKX"],
    "SHA": ["PVG", "SHA"],
    "WAS": ["IAD", "DCA", "BWI"],
    "CHI": ["ORD", "MDW"],
    "STO": ["ARN", "BMA"],
    "BUE": ["EZE", "AEP"],
}

_NORTH_SEASONS = {
    12: "winter", 1: "winter", 2: "winter",
    3: "spring", 4: "spring", 5: "spring",
    6: "summer", 7: "summer", 8: "summer",
    9: "autumn", 10: "autumn", 11: "autumn",
}
_FLIP = {"winter": "summer", "summer": "winter", "spring": "autumn", "autumn": "spring"}


# ---------------------------------------------------------------- airports ----
@lru_cache(maxsize=1)
def _airports() -> dict:
    return airportsdata.load("IATA")


def airport_info(iata: str | None) -> dict | None:
    """Full airportsdata record (name, city, country, lat, lon, tz) or None."""
    return _airports().get((iata or "").strip().upper())


def is_valid_iata(iata: str | None) -> bool:
    return airport_info(iata) is not None


def country_code_of_airport(iata: str | None) -> str | None:
    """ISO alpha-2 country code of an airport, e.g. 'BOM' -> 'IN'."""
    info = airport_info(iata)
    return info["country"] if info else None


def country_name(alpha2: str | None) -> str | None:
    """'IN' -> 'India'."""
    if not alpha2:
        return None
    c = pycountry.countries.get(alpha_2=alpha2.upper())
    return getattr(c, "common_name", None) or (c.name if c else alpha2)


def airport_to_place(iata: str | None) -> str | None:
    """'BOM' -> 'Mumbai, India'. None if the code is unknown."""
    info = airport_info(iata)
    if not info:
        return None
    return f"{info['city']}, {country_name(info['country'])}"


# Main airport for well-known cities (airportsdata has no traffic data to rank by).
PREFERRED_CITY_AIRPORT: dict[str, str] = {
    "london": "LHR", "new york": "JFK", "paris": "CDG", "tokyo": "HND", "milan": "MXP",
    "rome": "FCO", "beijing": "PEK", "shanghai": "PVG", "washington": "IAD", "chicago": "ORD",
    "mumbai": "BOM", "bombay": "BOM", "delhi": "DEL", "new delhi": "DEL", "bangalore": "BLR",
    "bengaluru": "BLR", "kolkata": "CCU", "chennai": "MAA", "goa": "GOI", "jaipur": "JAI",
    "dubai": "DXB", "istanbul": "IST", "bangkok": "BKK", "kuala lumpur": "KUL", "singapore": "SIN",
    "sydney": "SYD", "toronto": "YYZ", "edinburgh": "EDI", "manchester": "MAN", "glasgow": "GLA",
}


def find_airport_for_city(place: str | None) -> str | None:
    """Best-guess main airport for a city name ('Mumbai, India' -> 'BOM'). None if not found."""
    if not place:
        return None
    city = place.split(",")[0].strip().lower()
    if city in PREFERRED_CITY_AIRPORT:
        return PREFERRED_CITY_AIRPORT[city]
    best, best_score = None, -1
    for code, a in _airports().items():
        if (a.get("city") or "").strip().lower() != city:
            continue
        name = (a.get("name") or "").lower()
        score = 2 * ("international" in name) + ("airport" in name)
        if score > best_score:
            best, best_score = code, score
    return best


def alternative_origins(iata: str) -> list[str]:
    """The airport first, then the other airports in its metro area (if any)."""
    code = iata.strip().upper()
    for airports in METRO_AIRPORTS.values():
        if code in airports:
            return [code] + [a for a in airports if a != code]
    return [code]


# --------------------------------------------------------------- countries ----
def is_country(name: str | None) -> bool:
    """True if the text is a country name/code ('India', 'UK', 'Japan', 'IN')."""
    if not name:
        return False
    text = name.split(",")[0].strip()
    if text.lower() in {"singapore", "monaco", "hong kong", "macau", "vatican", "vatican city"}:
        return False  # city-states: treat as cities
    aliases = {"uk": "GB", "u.k.": "GB", "britain": "GB", "england": "GB", "scotland": "GB",
               "wales": "GB", "usa": "US", "u.s.": "US", "america": "US", "uae": "AE"}
    if text.lower() in aliases:
        return True
    try:
        pycountry.countries.lookup(text)
        return True
    except LookupError:
        return False


# ----------------------------------------------------------------- seasons ----
def month_name(month: int) -> str:
    return calendar.month_name[month]


def season_for(month: int, latitude: float) -> str:
    """Meteorological season for a month at a latitude (southern hemisphere flipped)."""
    season = _NORTH_SEASONS[month]
    return _FLIP[season] if latitude < 0 else season


def season_for_airport(iata: str | None, month: int, default_lat: float = 51.0) -> str:
    """Season at an airport's location for a month."""
    info = airport_info(iata)
    lat = float(info["lat"]) if info else default_lat
    return season_for(month, lat)


# ---------------------------------------------------------- trip planning ----
def allocate_days(places: list[dict], total_days: int, min_days: int = 2) -> list[dict]:
    """
    Split total_days across places already sorted by priority.
    At least `min_days` per stop; spare days go to the top-priority stops.

        allocate_days([{"name": "Goa"}, {"name": "Jaipur"}, {"name": "Agra"}], 5)
        -> [{"name": "Goa", "days": 3}, {"name": "Jaipur", "days": 2}]
    """
    if not places or total_days <= 0:
        return []
    n = max(1, min(len(places), total_days // max(1, min_days)))
    stops = [dict(p) for p in places[:n]]
    base, extra = divmod(total_days, n)
    for i, stop in enumerate(stops):
        stop["days"] = base + (1 if i < extra else 0)
    return stops
