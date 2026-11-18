"""
Run the full pipeline end to end, showing each node as it finishes.

    uv run python scripts/run.py "plan me a 5 days trip"
    uv run python scripts/run.py "suggest a 5 day trip from uk to india"
    uv run python scripts/run.py "4 days in Edinburgh" --quiet
"""

import argparse
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # make travel_agent importable

from travel_agent.graph import build_graph  # noqa: E402

SHOW = ("destination_type", "destination_name", "from_iata", "to_iata",
        "departure_date", "trip_days", "season")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("query", help="travel request in plain English")
    p.add_argument("--quiet", action="store_true", help="only print the final itinerary")
    args = p.parse_args()

    graph = build_graph()
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    inputs = {"user_query": args.query, "messages": [], "llm_calls": 0}

    start = last = time.time()
    for chunk in graph.stream(inputs, config=config, stream_mode="updates"):
        for node, update in chunk.items():
            now = time.time()
            if not args.quiet:
                print(f"\n[{now - start:6.1f}s] {node} (+{now - last:.1f}s)")
                for key in SHOW:
                    if update and key in update:
                        print(f"    {key}: {update[key]}")
                if update and update.get("plan_stops"):
                    for s in update["plan_stops"]:
                        print(f"    stop: {s['name']} ({s.get('iata')}) - {s.get('days')} day(s)")
                if update and "flight_results" in update:
                    print("    flights:", update["flight_results"].splitlines()[0][:100])
            last = now

    final = graph.get_state(config).values
    print("\n" + "=" * 70)
    print(final.get("itinerary", "(no itinerary produced)"))
    print("=" * 70)
    print(f"Total {time.time() - start:.1f}s | LLM calls: {final.get('llm_calls')}")


if __name__ == "__main__":
    main()
