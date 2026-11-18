"""
Tavily web search helpers for hotels and places.

    from travel_agent.tools import search_hotels, search_places
    print(search_hotels("Mumbai, India"))
    print(search_places("India", "November"))

Requires:  uv add tavily-python    and TAVILY_API_KEY in .env.
"""

import logging
import re
from functools import lru_cache

from langsmith import traceable

from .. import config
from .cache import cached

log = logging.getLogger("travel_agent.hotels")

# Hotel searches are limited to these sites, so news and unrelated pages are excluded.
HOTEL_DOMAINS = (
    "booking.com", "tripadvisor.com", "tripadvisor.co.uk", "hotels.com",
    "expedia.co.uk", "agoda.com", "kayak.co.uk", "lonelyplanet.com", "timeout.com",
)

# Button labels and amenity words that add noise but no information.
_NOISE = re.compile(
    r"\b(Check availability|Show all \d+ hotels|Free Wi-?Fi|Parking|Pool|Spa|See prices|View deal)\b",
    re.IGNORECASE,
)


@lru_cache(maxsize=1)
def _client():
    from tavily import TavilyClient   # imported lazily so the package loads without the key
    if not config.TAVILY_API_KEY:
        raise RuntimeError("TAVILY_API_KEY is not set")
    return TavilyClient(api_key=config.TAVILY_API_KEY)


def _clean(text: str) -> str:
    """Remove markdown symbols, button text and repeated lines from a search snippet."""
    text = re.sub(r"[#*_>|]+", " ", text or "")
    text = _NOISE.sub(" ", text)
    lines, seen = [], set()
    for line in (part.strip() for part in text.splitlines()):
        key = line.lower()
        if line and key not in seen:
            seen.add(key)
            lines.append(line)
    return re.sub(r"\s+", " ", " ".join(lines)).strip()


@traceable(run_type="tool", name="tavily_search")
@cached(ttl_seconds=config.SEARCH_CACHE_TTL,
        cache_if=lambda r: isinstance(r, str) and not r.startswith("Search failed"))
def tavily_search(
    query: str,
    max_results: int = 5,
    snippet_chars: int = 300,
    include_domains: tuple[str, ...] | None = None,
) -> str:
    """Web search returning numbered 'title / url / snippet' blocks. Never raises."""
    try:
        response = _client().search(
            query=query,
            max_results=max_results,
            topic="general",
            include_domains=list(include_domains) if include_domains else None,
            include_answer=False,
            include_raw_content=False,
        )
    except Exception as exc:  # network, quota, bad key...
        log.warning("Tavily search failed for %r: %s", query, exc)
        return f"Search failed: {exc}"

    results = []
    for i, r in enumerate(response.get("results", []), 1):
        title = r.get("title", "Unknown")
        url = r.get("url", "")
        snippet = _clean(r.get("content") or "")
        if len(snippet) > snippet_chars:
            snippet = snippet[:snippet_chars].rsplit(" ", 1)[0] + "..."
        results.append(f"{i}. {title}\n   {url}\n   {snippet}")

    log.info("Tavily %r: %d results", query, len(results))
    return "\n\n".join(results) if results else "No results found."


def search_hotels(place: str, budget: str = "affordable") -> str:
    """Hotel suggestions for one place, from travel and booking sites only."""
    return tavily_search(
        f"{budget} hotels in {place} with neighbourhood and nightly price",
        include_domains=HOTEL_DOMAINS,
    )


def search_places(country: str, month: str) -> str:
    """Research text for ranking places to visit in a country in a given month."""
    return tavily_search(f"best places to visit in {country} in {month}, must-see destinations")