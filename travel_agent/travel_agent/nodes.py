"""
Graph nodes.

Flow:
    extract_trip --route--> suggest_destination ─┐
                       ├--> plan_country ─────────┼--> prepare_search --> search_flight ─┐
                       └--> (city) ───────────────┘                  └--> search_hotel ──┴--> build_itinerary
"""

import logging
from datetime import date, timedelta
from typing import Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field, field_validator

from . import config
from .llm import get_extract_llm, get_itinerary_llm
from .state import TravelState
from .tools import (
    airport_info,
    airport_to_place,
    allocate_days,
    country_code_of_airport,
    country_name,
    find_airport_for_city,
    flight_tool,
    is_country,
    is_valid_iata,
    month_name,
    search_hotels,
    search_places,
    season_for_airport,
)

log = logging.getLogger("travel_agent.nodes")


# ------------------------------------------------------------------ schemas ----
_NULL_STRINGS = {"", "null", "none", "n/a", "na", "nil", "unknown", "not mentioned", "not specified"}

class TripQuery(BaseModel):
    from_iata: str | None = Field(None, description="3-letter IATA of the departure airport, or null if not mentioned.")
    destination: str | None = Field(None, description="Destination in plain words (city or country), or null if none.")
    to_iata: str | None = Field(None, description="Destination airport IATA if a city is given, else null.")
    departure_date: str | None = Field(None, description="YYYY-MM-DD if mentioned, else null.")
    trip_days: int | None = Field(None, description="Number of trip days if mentioned, else null.")

    @field_validator("from_iata", "destination", "to_iata", "departure_date", "trip_days", mode="before")    
    @classmethod
    def _text_null_to_none(cls, v):

            
        if isinstance(v, str) and v.strip().lower() in _NULL_STRINGS:
            return None
        return v

class DestinationPick(BaseModel):
    destination_name: str = Field(description="City or region, country")
    to_iata: str = Field(description="IATA code of the nearest airport")
    reason: str


class Place(BaseModel):
    name: str
    iata: str = Field(description="Nearest airport IATA code")
    must_visit_rank: int = Field(description="1 = most must-visit")
    best_months: list[int] = Field(description="Best months to visit, numbers 1-12")
    reason: str


class CountryPlaces(BaseModel):
    places: list[Place]


EXTRACT_PROMPT = """Extract the travel request details.

Rules:
- destination: where the traveller wants to GO (city or country), in plain words. null if not mentioned.
- to_iata: 3-letter IATA of the destination's main airport, only if a city is given.
- from_iata: 3-letter IATA of where they leave FROM, or null if not mentioned.
- departure_date: YYYY-MM-DD if mentioned, else null.
- trip_days: number of days if mentioned, else null.

Examples:
"plan me a 5 days trip" -> destination: null, to_iata: null, from_iata: null, trip_days: 5
"5 day trip from uk to india" -> destination: "India", to_iata: null, from_iata: "LHR", trip_days: 5
"Bombay" -> destination: "Mumbai", to_iata: "BOM", from_iata: null
"Manchester to Tokyo on 2026-12-20 for a week" -> from_iata: "MAN", destination: "Tokyo", to_iata: "NRT", departure_date: "2026-12-20", trip_days: 7

User request: "{query}"
"""


# -------------------------------------------------------------------- nodes ----
def extract_trip(state: TravelState) -> dict:
    """Small model extracts raw fields; Python decides the type and validates codes."""
    query = state["user_query"]
    t = get_extract_llm().with_structured_output(TripQuery).invoke(EXTRACT_PROMPT.format(query=query))
    log.info("extracted: %s", t)

    from_code = (t.from_iata or "").upper()
    if not is_valid_iata(from_code):
        from_code = config.DEFAULT_ORIGIN

    dep_date = t.departure_date
    try:
        date.fromisoformat(dep_date or "")
    except ValueError:
        dep_date = (date.today() + timedelta(days=config.DEFAULT_DAYS_AHEAD)).isoformat()

    # Decide the request type in code (small models mislabel this).
    dest = (t.destination or "").strip() or None
    if not dest:
        dtype, to_code = "none", None
    elif is_country(dest):
        dtype, to_code = "country", None
    else:
        dtype = "city"
        to_code = (t.to_iata or "").upper()
        if not is_valid_iata(to_code):
            to_code = find_airport_for_city(dest)

    days = t.trip_days if t.trip_days and 1 <= t.trip_days <= 30 else config.DEFAULT_TRIP_DAYS
    month = int(dep_date[5:7])

    result = {
        "from_iata": from_code,
        "destination_type": dtype,
        "destination_name": airport_to_place(to_code) if dtype == "city" and to_code else dest,
        "to_iata": to_code,
        "departure_date": dep_date,
        "trip_days": days,
        "season": season_for_airport(to_code or from_code, month),
        "plan_stops": [],
        "llm_calls": 1,
    }
    log.info("trip: %s", {k: v for k, v in result.items() if k != "plan_stops"})
    return result


def route_destination(state: TravelState) -> Literal["suggest_destination", "plan_country", "prepare_search"]:
    return {"none": "suggest_destination", "country": "plan_country"}.get(
        state.get("destination_type"), "prepare_search"
    )


def suggest_destination(state: TravelState) -> dict:
    """No destination given: pick one place in the home country that suits the season."""
    home = airport_info(state["from_iata"]) or {}
    home_cc = home.get("country") or country_code_of_airport(config.DEFAULT_ORIGIN)
    home_country = country_name(home_cc)
    month = month_name(int(state["departure_date"][5:7]))

    pick = get_itinerary_llm().with_structured_output(DestinationPick).invoke(
        f"""The traveller lives near {home.get('city', 'home')}, {home_country}.
They want a {state['trip_days']}-day trip in {month} ({state.get('season')}).
Suggest ONE destination inside {home_country} (not {home.get('city')}) that is genuinely good in {month},
considering weather, daylight and seasonal events. Give its nearest airport IATA code."""
    )
    log.info("suggested: %s", pick)

    code = pick.to_iata.upper()
    if not is_valid_iata(code) or country_code_of_airport(code) != home_cc:
        code = find_airport_for_city(pick.destination_name)
        if code and country_code_of_airport(code) != home_cc:
            code = None

    return {
        "destination_name": pick.destination_name,
        "to_iata": code,
        "plan_stops": [{"name": pick.destination_name, "iata": code,
                        "days": state["trip_days"], "reason": pick.reason}],
        "llm_calls": 1,
    }


def plan_country(state: TravelState) -> dict:
    """Country only: research, rank by must-visit, keep in-season places, split days."""
    country = state["destination_name"]
    month_num = int(state["departure_date"][5:7])
    month = month_name(month_num)

    research = search_places(country, month)
    result = get_itinerary_llm().with_structured_output(CountryPlaces).invoke(
        f"""Using the research below and your knowledge, list 6-8 notable places to visit in {country}.
Rank them by must-visit (1 = top) and give the best months to visit each (numbers 1-12).

Research:
{research}"""
    )

    places = [p.model_dump() for p in result.places]
    in_season = [p for p in places if month_num in p["best_months"]] or places
    in_season.sort(key=lambda p: p["must_visit_rank"])
    stops = allocate_days(in_season, state["trip_days"])

    for s in stops:
        code = (s.get("iata") or "").upper()
        s["iata"] = code if is_valid_iata(code) else find_airport_for_city(s["name"])
    log.info("route: %s", [(s["name"], s["iata"], s["days"]) for s in stops])

    first_with_airport = next((s for s in stops if s.get("iata")), None)
    return {
        "plan_stops": stops,
        "to_iata": first_with_airport["iata"] if first_with_airport else None,
        "llm_calls": 1,
    }


def prepare_search(state: TravelState) -> dict:
    """Join point before the parallel searches."""
    log.info("searching for %s (%s)", state.get("destination_name"), state.get("to_iata"))
    return {}


def search_flight(state: TravelState) -> dict:
    if not state.get("to_iata"):
        flights = "No destination airport identified, so no flight search was made."
    else:
        flights = flight_tool(state["from_iata"], state["to_iata"], state["departure_date"])
    return {"flight_results": flights, "messages": [AIMessage(content="Flight data added")]}


def search_hotel(state: TravelState) -> dict:
    stops = state.get("plan_stops") or [{"name": state.get("destination_name")}]
    parts = [f"## {s['name']}\n{search_hotels(s['name'])}" for s in stops[:3] if s.get("name")]
    return {"hotel_results": "\n\n".join(parts) or "No hotel data.",
            "messages": [AIMessage(content="Hotel data added")]}


def build_itinerary(state: TravelState) -> dict:
    stops = state.get("plan_stops") or []
    route = "\n".join(f"- {s['name']}: {s['days']} day(s) — {s.get('reason', '')}" for s in stops) \
        or f"- {state.get('destination_name')}: {state['trip_days']} days"

    prompt = f"""Trip: {state['trip_days']} days, departing {state['departure_date']} ({state.get('season')}),
flying FROM {airport_to_place(state['from_iata']) or state['from_iata']}.

Planned route (follow these stops and day counts, in this order):
{route}

Flights to the first stop:
{state.get('flight_results', 'No flight data.')}

Hotels:
{state.get('hotel_results', 'No hotel data.')}

Original request: {state['user_query']}

Write a practical, affordable day-by-day itinerary for the days spent AT the destination(s),
not at the departure city. Day 1 = arrival. Include travel between stops, one or two hotel
suggestions per stop from the data, and seasonal tips. Keep it under 400 words."""

    response = get_itinerary_llm().invoke([
        SystemMessage(content="You are a professional travel advisor with 10+ years of experience."),
        HumanMessage(content=prompt),
    ])
    return {"itinerary": response.content, "messages": [response], "llm_calls": 1}
