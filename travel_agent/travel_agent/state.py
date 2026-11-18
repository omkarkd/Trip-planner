"""Graph state shared by all nodes."""

import operator
from typing import Annotated

from langchain_core.messages import AnyMessage
from typing_extensions import TypedDict


class TravelState(TypedDict, total=False):
    # input
    messages: Annotated[list[AnyMessage], operator.add]
    user_query: str

    # filled by extract_trip
    from_iata: str
    destination_type: str          # "none" | "country" | "city"
    destination_name: str | None
    to_iata: str | None
    departure_date: str            # YYYY-MM-DD
    trip_days: int
    season: str

    # filled by suggest_destination / plan_country
    plan_stops: list[dict]         # [{"name", "iata", "days", "reason"}]

    # filled by search nodes
    flight_results: str
    hotel_results: str

    # output
    itinerary: str
    llm_calls: Annotated[int, operator.add]
