"""
Run LangSmith evaluations.

    uv run python evals/run_evals.py --suite extraction        # fast: ~15 cases x a few seconds
    uv run python evals/run_evals.py --suite full              # slow: 4 cases x 1-4 minutes
    uv run python evals/run_evals.py --suite extraction --recreate   # rebuild the dataset after editing cases.py

Results appear in LangSmith under Datasets & Experiments -> <dataset name> -> Experiments,
where you can compare runs side by side (e.g. before/after a prompt change).
"""

import argparse
import sys
import time
import uuid
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))        # make travel_agent and evals importable

from langsmith import Client                       # noqa: E402
from langsmith.evaluation import evaluate          # noqa: E402

from evals.cases import EXTRACTION_CASES, FULL_CASES                     # noqa: E402
from evals.evaluators import EXTRACTION_EVALUATORS, FULL_EVALUATORS      # noqa: E402
from travel_agent import config                                          # noqa: E402

SUITES = {
    "extraction": ("trip-planner-extraction", EXTRACTION_CASES, EXTRACTION_EVALUATORS),
    "full": ("trip-planner-e2e", FULL_CASES, FULL_EVALUATORS),
}


# ---------------------------------------------------------------- targets ----
def extraction_target(inputs: dict) -> dict:
    from travel_agent.nodes import extract_trip
    out = extract_trip({"user_query": inputs["query"]})
    return {k: out.get(k) for k in ("destination_type", "destination_name", "to_iata",
                                     "from_iata", "trip_days", "departure_date", "season")}


_graph = None


def full_target(inputs: dict) -> dict:
    global _graph
    if _graph is None:
        from travel_agent.graph import build_graph
        _graph = build_graph()
    start = time.time()
    final = _graph.invoke(
        {"user_query": inputs["query"], "messages": [], "llm_calls": 0},
        config={"configurable": {"thread_id": str(uuid.uuid4())}},
    )
    return {
        "itinerary": final.get("itinerary"),
        "destination_type": final.get("destination_type"),
        "destination_name": final.get("destination_name"),
        "to_iata": final.get("to_iata"),
        "trip_days": final.get("trip_days"),
        "plan_stops": final.get("plan_stops"),
        "llm_calls": final.get("llm_calls"),
        "seconds": round(time.time() - start, 1),
    }


TARGETS = {"extraction": extraction_target, "full": full_target}


# ---------------------------------------------------------------- dataset ----
def ensure_dataset(client: Client, name: str, cases: list[dict], recreate: bool) -> None:
    if client.has_dataset(dataset_name=name):
        if not recreate:
            print(f"Using existing dataset '{name}' (pass --recreate after editing cases.py)")
            return
        client.delete_dataset(dataset_name=name)
        print(f"Deleted dataset '{name}'")
    ds = client.create_dataset(dataset_name=name, description="Travel agent evaluation cases")
    client.create_examples(
        inputs=[c["inputs"] for c in cases],
        outputs=[c["outputs"] for c in cases],
        dataset_id=ds.id,
    )
    print(f"Created dataset '{name}' with {len(cases)} examples")


# ---------------------------------------------------------------- summary ----
def print_summary(results) -> None:
    scores = defaultdict(list)
    failures = []
    for row in results:
        query = (row["example"].inputs or {}).get("query")
        for res in row["evaluation_results"]["results"]:
            if res.score is None:
                continue
            scores[res.key].append(float(res.score))
            if not res.score:
                failures.append(f"  - [{res.key}] {query!r}: {res.comment}")
    print("\nScore per check:")
    for key, vals in scores.items():
        print(f"  {key:22s} {sum(vals) / len(vals):5.0%}  ({int(sum(vals))}/{len(vals)})")
    if failures:
        print("\nFailures:")
        print("\n".join(failures))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--suite", choices=list(SUITES), default="extraction")
    p.add_argument("--recreate", action="store_true", help="rebuild the dataset from cases.py")
    p.add_argument("--prefix", default=None, help="experiment name prefix, e.g. 'prompt-v2'")
    args = p.parse_args()

    dataset, cases, evaluators = SUITES[args.suite]
    client = Client()
    ensure_dataset(client, dataset, cases, args.recreate)

    results = evaluate(
        TARGETS[args.suite],
        data=dataset,
        evaluators=evaluators,
        experiment_prefix=args.prefix or args.suite,
        max_concurrency=1,          # the Oracle CPU handles one heavy request well at a time
        metadata={
            "extract_model": config.EXTRACT_MODEL,
            "itinerary_model": config.ITINERARY_MODEL,
            "ollama": config.OLLAMA_BASE_URL,
        },
    )
    print_summary(results)


if __name__ == "__main__":
    main()
