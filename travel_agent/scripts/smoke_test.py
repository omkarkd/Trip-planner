"""
Layer-by-layer checks, cheapest first. Stops explaining at the first failure.

    uv run python scripts/smoke_test.py              # everything (uses 1 OAG + 1 Tavily call, cached after)
    uv run python scripts/smoke_test.py --no-paid    # skip OAG and Tavily
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # make travel_agent importable

results: list[tuple[str, bool, str]] = []


def check(name: str):
    def deco(fn):
        def run():
            t0 = time.time()
            try:
                detail = fn() or ""
                results.append((name, True, f"{detail} ({time.time() - t0:.1f}s)"))
                print(f"PASS  {name}: {detail}")
            except Exception as exc:
                results.append((name, False, f"{type(exc).__name__}: {exc}"))
                print(f"FAIL  {name}: {type(exc).__name__}: {exc}")
        return run
    return deco


@check("1. config / .env")
def t_config():
    from travel_agent import config
    missing = [k for k in ("OLLAMA_BASE_URL", "OAG_FLIGHT_API_KEY", "TAVILY_API_KEY")
               if not getattr(config, k)]
    assert not missing, f"missing in {config.ENV_FILE}: {missing}"
    return f"{config.ENV_FILE} -> Ollama {config.OLLAMA_BASE_URL}"


@check("2. geo helpers")
def t_geo():
    from travel_agent.tools import (airport_to_place, allocate_days, find_airport_for_city,
                                    is_country, season_for_airport)
    assert airport_to_place("BOM").startswith("Mumbai"), airport_to_place("BOM")
    assert is_country("India") and is_country("UK") and not is_country("Mumbai")
    assert find_airport_for_city("Bombay") == "BOM"
    assert season_for_airport("SYD", 1) == "summer"
    assert [s["days"] for s in allocate_days([{"name": "a"}, {"name": "b"}, {"name": "c"}], 5)] == [3, 2]
    return "airports, countries, seasons, day split OK"


@check("3. cache")
def t_cache():
    from travel_agent.tools import cached, clear_cache
    calls = []

    @cached(ttl_seconds=60, namespace="_smoke")
    def f(x):
        calls.append(x)
        return {"x": x}

    f(1); f(1)
    clear_cache("_smoke")
    assert calls == [1], calls
    return "second call served from cache"


@check("4. LLM extract model (Oracle)")
def t_llm_extract():
    from travel_agent import config
    from travel_agent.llm import ping
    reply = ping()
    assert reply.strip(), "empty reply"
    return f"{config.EXTRACT_MODEL} replied {reply.strip()[:30]!r}"


@check("5. extraction node")
def t_extract():
    from travel_agent.nodes import extract_trip
    out = []
    for q, expected in [("plan me a 5 days trip", "none"),
                        ("5 day trip from uk to india", "country"),
                        ("4 days in Edinburgh", "city")]:
        r = extract_trip({"user_query": q})
        out.append(f"{expected}->{r['destination_type']}/{r.get('to_iata')}")
        assert r["destination_type"] == expected, f"{q!r}: got {r['destination_type']}"
    return ", ".join(out)


@check("6. flights (OAG)")
def t_flights():
    from travel_agent.tools import flight_tool
    from datetime import date, timedelta
    d = (date.today() + timedelta(days=7)).isoformat()
    text = flight_tool("LGW", "EDI", d)
    assert "|" in text, text[:200]
    return f"{len(text.splitlines())} flights LGW->EDI on {d}"


@check("7. hotels (Tavily)")
def t_hotels():
    from travel_agent.tools import search_hotels
    text = search_hotels("Edinburgh, United Kingdom")
    assert not text.startswith("Search failed"), text[:200]
    return f"{text.count('http')} results"


@check("8. graph compiles")
def t_graph():
    from travel_agent.graph import build_graph
    g = build_graph()
    return f"{len(g.get_graph().nodes)} nodes"


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--no-paid", action="store_true", help="skip OAG and Tavily calls")
    args = p.parse_args()

    tests = [t_config, t_geo, t_cache, t_llm_extract, t_extract]
    if not args.no_paid:
        tests += [t_flights, t_hotels]
    tests += [t_graph]

    for t in tests:
        t()

    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed")
    sys.exit(1 if failed else 0)
