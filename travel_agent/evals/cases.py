"""
Test cases. Each case = inputs (what the user types) + reference outputs (what a correct run produces).

Reference conventions:
- to_iata:      list of acceptable codes, or None when no airport is expected (country / no destination).
                Leave the key out to skip the check.
- from_iata:    list of acceptable codes. Leave out to skip.
- trip_days:    exact int. Leave out to skip.
- departure_date: "YYYY-MM-DD". Leave out to skip.
"""

LONDON = ["LGW", "LHR", "STN", "LTN", "LCY", "SEN"]

# Fast suite: runs only the extraction node (a few seconds per case, no OAG/Tavily calls).
EXTRACTION_CASES: list[dict] = [
    # ---- no destination ----
    {"inputs": {"query": "plan me a 5 days trip"},
     "outputs": {"destination_type": "none", "to_iata": None, "trip_days": 5}},
    {"inputs": {"query": "I need a holiday, surprise me"},
     "outputs": {"destination_type": "none", "to_iata": None}},
    {"inputs": {"query": "suggest somewhere for a 3 day break"},
     "outputs": {"destination_type": "none", "to_iata": None, "trip_days": 3}},

    # ---- country only ----
    {"inputs": {"query": "suggest a 5 day trip from uk to india"},
     "outputs": {"destination_type": "country", "to_iata": None, "trip_days": 5, "from_iata": LONDON}},
    {"inputs": {"query": "10 days in Japan"},
     "outputs": {"destination_type": "country", "to_iata": None, "trip_days": 10}},
    {"inputs": {"query": "family holiday to Spain"},
     "outputs": {"destination_type": "country", "to_iata": None}},
    {"inputs": {"query": "a week in Italy"},
     "outputs": {"destination_type": "country", "to_iata": None, "trip_days": 7}},

    # ---- city ----
    {"inputs": {"query": "4 days in Edinburgh"},
     "outputs": {"destination_type": "city", "to_iata": ["EDI"], "trip_days": 4}},
    {"inputs": {"query": "Bombay"},
     "outputs": {"destination_type": "city", "to_iata": ["BOM"]}},
    {"inputs": {"query": "Manchester to Tokyo on 2026-12-20 for a week"},
     "outputs": {"destination_type": "city", "to_iata": ["NRT", "HND"], "from_iata": ["MAN"],
                 "trip_days": 7, "departure_date": "2026-12-20"}},
    {"inputs": {"query": "fly from Gatwick to Kuala Lumpur"},
     "outputs": {"destination_type": "city", "to_iata": ["KUL"], "from_iata": ["LGW"]}},
    {"inputs": {"query": "3 days in Paris"},
     "outputs": {"destination_type": "city", "to_iata": ["CDG", "ORY"], "trip_days": 3}},
    {"inputs": {"query": "trip to New York for 6 days"},
     "outputs": {"destination_type": "city", "to_iata": ["JFK", "EWR", "LGA"], "trip_days": 6}},
    {"inputs": {"query": "Singapore for 4 days"},
     "outputs": {"destination_type": "city", "to_iata": ["SIN"], "trip_days": 4}},
    {"inputs": {"query": "Goa beach holiday 7 days"},
     "outputs": {"destination_type": "city", "to_iata": ["GOI", "GOX"], "trip_days": 7}},
]

# Full suite: runs the whole graph (1-4 minutes per case on the Oracle CPU; uses OAG + Tavily, cached).
FULL_CASES: list[dict] = [
    {"inputs": {"query": "4 days in Edinburgh"},
     "outputs": {"destination_type": "city", "trip_days": 4, "country": "GB"}},
    {"inputs": {"query": "plan me a 5 days trip"},
     "outputs": {"destination_type": "none", "trip_days": 5, "country": "GB"}},
    {"inputs": {"query": "suggest a 5 day trip from uk to india"},
     "outputs": {"destination_type": "country", "trip_days": 5, "country": "IN"}},
    {"inputs": {"query": "3 days in Paris"},
     "outputs": {"destination_type": "city", "trip_days": 3, "country": "FR"}},
]
