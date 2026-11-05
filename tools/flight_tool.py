"""
Flight price search using FlightAPI.io (one-way trip endpoint).

Replaces the old AviationStack "live flight status" integration.

.env:
    FLIGHT_API_KEY=your_flightapi_io_key
    DEFAULT_ORIGIN_IATA=DAC        # optional, used when the query names only a destination
    DEFAULT_CURRENCY=USD           # optional
    DEFAULT_DAYS_AHEAD=7           # optional, used when the query has no date
"""

import os
import re
from datetime import date, timedelta

import airportsdata
import certifi
import pycountry
import requests
from dotenv import load_dotenv

load_dotenv()

os.environ["SSL_CERT_FILE"] = certifi.where()
os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()

API_KEY = os.getenv("FLIGHT_API_KEY")

# Default origin when user says only destination, e.g. "Japan trip"
DEFAULT_ORIGIN_IATA = os.getenv("DEFAULT_ORIGIN_IATA", "DAC")
DEFAULT_CURRENCY = os.getenv("DEFAULT_CURRENCY", "USD").upper()
DEFAULT_DAYS_AHEAD = int(os.getenv("DEFAULT_DAYS_AHEAD", "7"))

BASE_URL = (
    "https://api.flightapi.io/onewaytrip/{api_key}/{dep}/{arr}/{date}/"
    "{adults}/{children}/{infants}/{cabin}/{currency}"
)

# FlightAPI responses can take a while (it scrapes several sources)
REQUEST_TIMEOUT = 60

# Relative booking links in the response point at Skyscanner
BOOKING_LINK_BASE = "https://www.skyscanner.net"

AIRPORTS = airportsdata.load("IATA")


COUNTRY_ALIASES = {
    "usa": "US",
    "u.s.a": "US",
    "u.s.": "US",
    "america": "US",
    "united states": "US",
    "uk": "GB",
    "u.k.": "GB",
    "britain": "GB",
    "england": "GB",
    "uae": "AE",
    "dubai": "AE",
    "south korea": "KR",
    "korea": "KR",
    "russia": "RU",
    "vietnam": "VN",
    "bangladesh": "BD",
    "india": "IN",
    "japan": "JP",
    "china": "CN",
    "singapore": "SG",
    "malaysia": "MY",
    "thailand": "TH",
    "indonesia": "ID",
    "nepal": "NP",
    "qatar": "QA",
    "saudi arabia": "SA",
    "turkey": "TR",
    "canada": "CA",
    "australia": "AU",
    "germany": "DE",
    "france": "FR",
    "italy": "IT",
    "spain": "ES",
}

# Preferred main airport for country-level search
COUNTRY_MAIN_AIRPORT = {
    "BD": "DAC",
    "IN": "DEL",
    "JP": "NRT",
    "US": "JFK",
    "GB": "LHR",
    "AE": "DXB",
    "SG": "SIN",
    "MY": "KUL",
    "TH": "BKK",
    "ID": "CGK",
    "CN": "PEK",
    "KR": "ICN",
    "NP": "KTM",
    "QA": "DOH",
    "SA": "JED",
    "TR": "IST",
    "CA": "YYZ",
    "AU": "SYD",
    "DE": "FRA",
    "FR": "CDG",
    "IT": "FCO",
    "ES": "MAD",
}

CITY_MAIN_AIRPORT = {
    "dhaka": "DAC",
    "delhi": "DEL",
    "new delhi": "DEL",
    "mumbai": "BOM",
    "kolkata": "CCU",
    "chennai": "MAA",
    "bangalore": "BLR",
    "bengaluru": "BLR",
    "tokyo": "NRT",
    "osaka": "KIX",
    "kyoto": "KIX",
    "new york": "JFK",
    "london": "LHR",
    "dubai": "DXB",
    "singapore": "SIN",
    "kuala lumpur": "KUL",
    "bangkok": "BKK",
    "doha": "DOH",
    "istanbul": "IST",
    "toronto": "YYZ",
    "sydney": "SYD",
    "paris": "CDG",
    "rome": "FCO",
    "madrid": "MAD",
    "frankfurt": "FRA",
}

# Currencies we recognise in a query ("... in BDT"). Kept explicit so that
# three-letter airport codes are not mistaken for currencies and vice versa.
CURRENCY_CODES = {
    "USD", "EUR", "GBP", "BDT", "INR", "JPY", "AED", "SGD", "MYR", "THB",
    "IDR", "CNY", "KRW", "NPR", "QAR", "SAR", "TRY", "CAD", "AUD", "CHF",
}

CABIN_CLASSES = [
    # (regex, FlightAPI value) - most specific first
    (r"premium[\s_-]*economy", "Premium_Economy"),
    (r"business", "Business"),
    (r"first[\s_-]*class", "First"),
    (r"economy", "Economy"),
]

MONTHS = {
    m: i
    for i, names in enumerate(
        [
            ("jan", "january"), ("feb", "february"), ("mar", "march"),
            ("apr", "april"), ("may",), ("jun", "june"), ("jul", "july"),
            ("aug", "august"), ("sep", "sept", "september"),
            ("oct", "october"), ("nov", "november"), ("dec", "december"),
        ],
        start=1,
    )
    for m in names
}
MONTH_RE = "|".join(sorted(MONTHS, key=len, reverse=True))


# ---------------------------------------------------------------------------
# Location resolution (unchanged logic, provider independent)
# ---------------------------------------------------------------------------

def clean_text(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text)
    stop_words = [
        "flight", "flights", "ticket", "tickets", "trip", "travel",
        "plan", "complete", "days", "day", "including", "hotel",
        "hotels", "sightseeing", "under", "budget", "info", "information",
        "cheap", "cheapest", "price", "prices", "fare", "fares",
    ]
    words = [w for w in text.split() if w not in stop_words]
    return " ".join(words).strip()


def country_name_to_code(text: str):
    text = clean_text(text)

    if text in COUNTRY_ALIASES:
        return COUNTRY_ALIASES[text]

    try:
        country = pycountry.countries.lookup(text)
        return country.alpha_2
    except LookupError:
        pass

    # Detect country name inside longer text (whole words only, so that
    # e.g. "niger" does not match inside "nigeria")
    for country in pycountry.countries:
        if re.search(rf"\b{re.escape(country.name.lower())}\b", text):
            return country.alpha_2

    for alias, code in COUNTRY_ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", text):
            return code

    return None


def airport_country_matches(airport: dict, country_code: str) -> bool:
    airport_country = str(airport.get("country", "")).upper().strip()

    if airport_country == country_code:
        return True

    country = pycountry.countries.get(alpha_2=country_code)
    return bool(country and airport_country.lower() == country.name.lower())


def get_best_airport_for_country(country_code: str):
    preferred = COUNTRY_MAIN_AIRPORT.get(country_code)

    if preferred and preferred in AIRPORTS:
        return preferred

    candidates = []

    for iata, airport in AIRPORTS.items():
        if not iata or not airport_country_matches(airport, country_code):
            continue

        name = str(airport.get("name", "")).lower()
        city = str(airport.get("city", "")).lower()

        score = 0
        if "international" in name:
            score += 50
        if "intl" in name:
            score += 40
        if "capital" in name:
            score += 20
        if city:
            score += 5

        candidates.append((score, iata))

    if not candidates:
        return None

    candidates.sort(reverse=True)
    return candidates[0][1]


def resolve_location_to_iata(location: str):
    """
    Converts country/city/airport/IATA into IATA code.

    Bangladesh -> DAC, Japan -> NRT, Dhaka -> DAC, Tokyo -> NRT, DAC -> DAC
    """
    if not location:
        return None

    raw_location = location.strip()

    # Direct IATA code
    if re.fullmatch(r"[A-Za-z]{3}", raw_location):
        code = raw_location.upper()
        if code in AIRPORTS and raw_location.lower() not in COUNTRY_ALIASES:
            return code

    location_clean = clean_text(raw_location)

    if not location_clean:
        return None

    if location_clean in CITY_MAIN_AIRPORT:
        return CITY_MAIN_AIRPORT[location_clean]

    country_code = country_name_to_code(location_clean)
    if country_code:
        airport = get_best_airport_for_country(country_code)
        if airport:
            return airport

    # Fuzzy city / airport-name match from the airport database
    city_matches = []

    for iata, airport in AIRPORTS.items():
        city = str(airport.get("city", "")).lower().strip()
        name = str(airport.get("name", "")).lower().strip()

        score = 0
        if city == location_clean:
            score += 100
        elif location_clean in city:
            score += 70
        if location_clean in name:
            score += 50
        if "international" in name:
            score += 10

        if score > 10:  # an "international" hit alone is not a match
            city_matches.append((score, iata))

    if city_matches:
        city_matches.sort(reverse=True)
        return city_matches[0][1]

    return None


def find_location_mentions(query: str):
    """Finds country or city names inside a natural language query, in order."""
    q = query.lower()
    found = []  # (position, name)

    for alias in COUNTRY_ALIASES:
        m = re.search(rf"\b{re.escape(alias)}\b", q)
        if m:
            found.append((m.start(), alias))

    for country in pycountry.countries:
        name = country.name.lower()
        if len(name) >= 4:
            m = re.search(rf"\b{re.escape(name)}\b", q)
            if m:
                found.append((m.start(), name))

    for city in CITY_MAIN_AIRPORT:
        m = re.search(rf"\b{re.escape(city)}\b", q)
        if m:
            found.append((m.start(), city))

    # Order by where they appear in the sentence, drop duplicates
    found.sort()
    mentions = []
    for _, name in found:
        if name not in mentions:
            mentions.append(name)
    return mentions


def _iata_codes_in(query: str):
    """Uppercase 3-letter words that are real airports (not USA/UAE/USD...)."""
    codes = []
    for code in re.findall(r"\b[A-Z]{3}\b", query):
        if (
            code in AIRPORTS
            and code not in CURRENCY_CODES
            and code.lower() not in COUNTRY_ALIASES
        ):
            codes.append(code)
    return codes


def parse_route(query: str):
    """
    Returns (dep_iata, arr_iata). Either may be None if it can't be found.
    A destination-only query gets DEFAULT_ORIGIN_IATA as the origin.
    """
    q = query.strip()
    q_lower = q.lower()

    codes = _iata_codes_in(q)
    if len(codes) >= 2:
        return codes[0], codes[1]

    end = r"(?:\s+(?:on|for|under|including|with|in|at|by)\b|[.,!?]|$)"
    dep_iata = arr_iata = None

    match = re.search(rf"\bfrom\s+(.+?)\s+to\s+(.+?){end}", q_lower)
    if match:
        dep_iata = resolve_location_to_iata(match.group(1))
        arr_iata = resolve_location_to_iata(match.group(2))
    else:
        match = re.search(rf"\bto\s+(.+?)\s+from\s+(.+?){end}", q_lower)
        if match:
            arr_iata = resolve_location_to_iata(match.group(1))
            dep_iata = resolve_location_to_iata(match.group(2))
        else:
            match = re.search(rf"\bfrom\s+(.+?){end}", q_lower)
            if match:
                dep_iata = resolve_location_to_iata(match.group(1))
            match = re.search(rf"\bto\s+(.+?){end}", q_lower)
            if match:
                arr_iata = resolve_location_to_iata(match.group(1))

    # Fill whatever is still missing from plain mentions,
    # e.g. "Plan a 7 days Japan trip from Bangladesh" -> Japan is the destination
    if not (dep_iata and arr_iata):
        mentioned = []
        for name in find_location_mentions(q):
            code = resolve_location_to_iata(name)
            if code and code not in mentioned:
                mentioned.append(code)
        mentioned += [c for c in codes if c not in mentioned]

        leftovers = [c for c in mentioned if c not in (dep_iata, arr_iata)]

        if dep_iata and not arr_iata and leftovers:
            arr_iata = leftovers[0]
        elif arr_iata and not dep_iata and leftovers:
            dep_iata = leftovers[0]
        elif not dep_iata and not arr_iata:
            if len(leftovers) >= 2:
                dep_iata, arr_iata = leftovers[0], leftovers[1]
            elif len(leftovers) == 1:
                arr_iata = leftovers[0]

    if arr_iata and not dep_iata:
        dep_iata = DEFAULT_ORIGIN_IATA

    return dep_iata, arr_iata


# ---------------------------------------------------------------------------
# Search options: date, passengers, cabin, currency
# ---------------------------------------------------------------------------

def _safe_date(year, month, day):
    try:
        return date(year, month, day)
    except ValueError:
        return None


def parse_travel_date(query: str, today: date = None):
    """
    Understands: 2026-12-10, 10/12/2026 (day first), 10 Dec, December 10 2026,
    today, tomorrow, next week, in 5 days. Returns (date or None, matched_text).
    A date without a year that has already passed this year rolls to next year.
    """
    today = today or date.today()
    q = query.lower()

    m = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", q)
    if m:
        return _safe_date(int(m[1]), int(m[2]), int(m[3])), m[0]

    m = re.search(r"\b(\d{1,2})[/.](\d{1,2})[/.](\d{4})\b", q)
    if m:
        return _safe_date(int(m[3]), int(m[2]), int(m[1])), m[0]

    def with_year(month, day, year):
        if year:
            return _safe_date(int(year), month, day)
        d = _safe_date(today.year, month, day)
        if d and d < today:
            d = _safe_date(today.year + 1, month, day)
        return d

    m = re.search(
        rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({MONTH_RE})\b,?(?:\s+(\d{{4}}))?", q
    )
    if m:
        return with_year(MONTHS[m[2]], int(m[1]), m[3]), m[0]

    m = re.search(rf"\b({MONTH_RE})\s+(\d{{1,2}})(?:st|nd|rd|th)?\b,?(?:\s+(\d{{4}}))?", q)
    if m:
        return with_year(MONTHS[m[1]], int(m[2]), m[3]), m[0]

    m = re.search(r"\bin\s+(\d{1,3})\s+days?\b", q)
    if m:
        return today + timedelta(days=int(m[1])), m[0]

    for word, delta in (("today", 0), ("tomorrow", 1), ("next week", 7)):
        if re.search(rf"\b{word}\b", q):
            return today + timedelta(days=delta), word

    return None, ""


def parse_passengers(query: str):
    q = query.lower()

    def count(pattern, default):
        m = re.search(rf"\b(\d+)\s+(?:{pattern})\b", q)
        return int(m[1]) if m else default

    adults = count(r"adults?|people|persons?|passengers?|travell?ers?|pax", 1)
    children = count(r"child|children|kids?", 0)
    infants = count(r"infants?|bab(?:y|ies)", 0)
    return max(adults, 1), children, infants


def parse_cabin_class(query: str):
    q = query.lower()
    for pattern, value in CABIN_CLASSES:
        if re.search(pattern, q):
            return value
    return "Economy"


def parse_currency(query: str):
    for word in re.findall(r"\b[A-Za-z]{3}\b", query):
        if word.upper() in CURRENCY_CODES and (
            word.isupper() or re.search(rf"\bin\s+{word}\b", query, re.I)
        ):
            return word.upper()
    return DEFAULT_CURRENCY


def parse_query(query: str, today: date = None):
    """Turns a natural-language request into FlightAPI search parameters."""
    today = today or date.today()

    travel_date, date_text = parse_travel_date(query, today)
    # Remove the date so "to Tokyo on 10 December" doesn't confuse the route parser
    route_query = re.sub(re.escape(date_text), " ", query, flags=re.I) if date_text else query

    dep_iata, arr_iata = parse_route(route_query)
    adults, children, infants = parse_passengers(query)

    return {
        "dep": dep_iata,
        "arr": arr_iata,
        "date": travel_date or today + timedelta(days=DEFAULT_DAYS_AHEAD),
        "date_given": travel_date is not None,
        "adults": adults,
        "children": children,
        "infants": infants,
        "cabin": parse_cabin_class(query),
        "currency": parse_currency(query),
    }


# ---------------------------------------------------------------------------
# FlightAPI.io request + response handling
# ---------------------------------------------------------------------------

def _redact(text: str) -> str:
    """The API key is part of the URL path; never show it in messages."""
    return text.replace(API_KEY, "***") if API_KEY else text


def _index_by_id(items):
    if isinstance(items, dict):  # some responses key objects by id already
        return {str(k): v for k, v in items.items()}
    return {str(item.get("id")): item for item in items or [] if isinstance(item, dict)}


def _place_label(place: dict):
    if not place:
        return "Unknown"
    name = place.get("name") or "Unknown"
    code = place.get("display_code") or place.get("iata") or place.get("alt_id")
    return f"{name} ({code})" if code else name


def _fmt_duration(minutes):
    if not isinstance(minutes, (int, float)):
        return "N/A"
    h, m = divmod(int(minutes), 60)
    return f"{h}h {m:02d}m"


def _fmt_time(value):
    if not value:
        return "Unknown"
    return str(value).replace("T", " ")[:16]


def _fmt_price(amount, currency):
    if not isinstance(amount, (int, float)):
        return "Price unavailable"
    return f"{amount:,.2f} {currency}"


def _option_price(option: dict):
    price = option.get("price") or {}
    amount = price.get("amount") if isinstance(price, dict) else price
    return amount if isinstance(amount, (int, float)) else None


def extract_itineraries(data: dict, currency: str):
    """Flattens FlightAPI's id-linked response into simple dicts, cheapest first."""
    legs = _index_by_id(data.get("legs"))
    places = _index_by_id(data.get("places"))
    carriers = _index_by_id(data.get("carriers"))
    agents = _index_by_id(data.get("agents"))
    segments = _index_by_id(data.get("segments"))

    results = []

    for itinerary in data.get("itineraries") or []:
        options = [o for o in itinerary.get("pricing_options") or [] if _option_price(o) is not None]
        if not options:
            continue
        best = min(options, key=_option_price)

        leg_ids = itinerary.get("leg_ids") or []
        leg = legs.get(str(leg_ids[0])) if leg_ids else None
        if not leg:
            continue

        airline_names = []
        for cid in leg.get("marketing_carrier_ids") or []:
            name = (carriers.get(str(cid)) or {}).get("name")
            if name and name not in airline_names:
                airline_names.append(name)

        flight_numbers = []
        for sid in leg.get("segment_ids") or []:
            seg = segments.get(str(sid)) or {}
            carrier = carriers.get(str(seg.get("marketing_carrier_id"))) or {}
            prefix = carrier.get("display_code") or ""
            number = seg.get("marketing_flight_number")
            if number:
                flight_numbers.append(f"{prefix}{number}")

        # stop_ids can be nested, e.g. [["13870"]] (city, then airport ids)
        stop_names = []
        for entry in leg.get("stop_ids") or []:
            ids = entry if isinstance(entry, list) else [entry]
            if ids:
                label = _place_label(places.get(str(ids[-1])))
                if label != "Unknown" and label not in stop_names:
                    stop_names.append(label)

        items = best.get("items") or []
        url = items[0].get("url") if items else None
        if url and url.startswith("/"):
            url = BOOKING_LINK_BASE + url

        agent_ids = best.get("agent_ids") or []
        agent = (agents.get(str(agent_ids[0])) or {}).get("name") if agent_ids else None

        origin_place = places.get(str(leg.get("origin_place_id"))) or {}
        dest_place = places.get(str(leg.get("destination_place_id"))) or {}

        results.append({
            "price": _option_price(best),
            "currency": currency,
            "airlines": airline_names or ["Unknown airline"],
            "flight_numbers": flight_numbers,
            "origin": _place_label(origin_place),
            "destination": _place_label(dest_place),
            "origin_airport": _airport_name(origin_place),
            "origin_iata": _place_code(origin_place),
            "destination_airport": _airport_name(dest_place),
            "destination_iata": _place_code(dest_place),
            "departure": leg.get("departure"),
            "arrival": leg.get("arrival"),
            "duration": leg.get("duration"),
            "stop_count": leg.get("stop_count"),
            "stops": stop_names,
            "agent": agent or "Unknown seller",
            "url": url,
        })

    results.sort(key=lambda r: r["price"])
    return results


def _place_code(place: dict):
    return place.get("display_code") or place.get("iata") or "Unknown"


def _airport_name(place: dict):
    """Full airport name from the airport database, else FlightAPI's place name."""
    code = place.get("display_code") or place.get("iata")
    if code and code in AIRPORTS and AIRPORTS[code].get("name"):
        return AIRPORTS[code]["name"]
    return place.get("name") or "Unknown airport"


def format_flight(it: dict):
    """Same layout as the original AviationStack output.

    FlightAPI is a fare search, so it has no live status, terminal, gate or
    delay data: those fields show "N/A" (status shows "Scheduled").
    """
    airline = ", ".join(it["airlines"]) or "Unknown airline"
    flight_number = ", ".join(it["flight_numbers"]) or "Unknown flight number"
    status = "Scheduled"
    price = _fmt_price(it["price"], it["currency"])

    return f"""
Airline: {airline}
Flight: {flight_number}
Status: {status}
Price: {price}

Departure:
- Airport: {it['origin_airport']}
- IATA: {it['origin_iata']}
- Terminal: N/A
- Gate: N/A
- Scheduled: {it['departure'] or 'Unknown'}
- Delay: N/A

Arrival:
- Airport: {it['destination_airport']}
- IATA: {it['destination_iata']}
- Terminal: N/A
- Gate: N/A
- Scheduled: {it['arrival'] or 'Unknown'}
- Delay: N/A
""".strip()


def search_flights(query: str, limit: int = 10):
    if not API_KEY:
        return (
            "Flight API error: FLIGHT_API_KEY is missing.\n"
            "Please add this in your .env file:\n"
            "FLIGHT_API_KEY=your_flightapi_io_key"
        )

    p = parse_query(query)

    if not p["dep"] or not p["arr"]:
        return (
            "Please tell me where you're flying from and to, e.g. "
            "'Dhaka to Tokyo on 10 December'.\n"
            "FlightAPI searches fares for one route and date at a time, "
            "so 'all flights' / worldwide searches aren't possible."
        )

    if p["dep"] == p["arr"]:
        return f"Origin and destination are both {p['dep']}. Please give two different places."

    if p["date"] < date.today():
        return f"The travel date {p['date']:%Y-%m-%d} is in the past."

    url = BASE_URL.format(
        api_key=API_KEY,
        dep=p["dep"],
        arr=p["arr"],
        date=p["date"].isoformat(),
        adults=p["adults"],
        children=p["children"],
        infants=p["infants"],
        cabin=p["cabin"],
        currency=p["currency"],
    )

    try:
        response = requests.get(url, timeout=REQUEST_TIMEOUT)
    except requests.exceptions.Timeout:
        return "Flight API request timed out. Please try again."
    except requests.exceptions.RequestException as e:
        return _redact(f"Flight API request failed: {e}")

    try:
        data = response.json()
    except ValueError:
        data = None

    if response.status_code != 200 or not isinstance(data, dict):
        message = None
        if isinstance(data, dict):
            message = data.get("message") or data.get("error") or data.get("detail")
        message = message or response.text[:300] or response.reason
        return _redact(
            f"Flight API error (HTTP {response.status_code}) for "
            f"{p['dep']} to {p['arr']} on {p['date']:%Y-%m-%d}:\n{message}"
        )

    itineraries = extract_itineraries(data, p["currency"])

    if not itineraries:
        return (
            f"No flight data found for route {p['dep']} to {p['arr']} "
            f"on {p['date']:%Y-%m-%d}."
        )

    route_info = f"Flights from {p['dep']} to {p['arr']}"

    formatted_flights = [format_flight(it) for it in itineraries[:limit]]

    return f"{route_info}\n\n" + "\n\n---\n\n".join(formatted_flights)


# if __name__ == "__main__":
#     print(search_flights("Plan a 7 days Japan trip from Bangladesh"))
#     print("\n" + "=" * 80 + "\n")
#     print(search_flights("Dhaka to London on 15 December for 2 adults in business class, prices in GBP"))