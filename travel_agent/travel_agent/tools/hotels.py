"""
Tavily web search helpers for hotels and places.

    from travel_agent.tools import search_hotels, search_places
    print(search_hotels("Mumbai, India"))
    print(search_places("India", "November"))

Requires:  uv add tavily-python    and TAVILY_API_KEY in .env.
"""

import logging
from functools import lru_cache

from .. import config
from .cache import cached

log = logging.getLogger("travel_agent.hotels")


@lru_cache(maxsize=1)
def _client():
    from tavily import TavilyClient   # imported lazily so the package loads without the key
    if not config.TAVILY_API_KEY:
        raise RuntimeError("TAVILY_API_KEY is not set")
    return TavilyClient(api_key=config.TAVILY_API_KEY)


@cached(ttl_seconds=config.SEARCH_CACHE_TTL, cache_if=lambda r: isinstance(r, str) and not r.startswith("Search failed"))
def tavily_search(query: str, max_results: int = 5, snippet_chars: int = 300) -> str:
    """Web search returning numbered 'title / url / snippet' blocks. Never raises."""
    try:
        response = _client().search(
            query=query,
            max_results=max_results,
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
        snippet = (r.get("content") or "").strip()
        if len(snippet) > snippet_chars:
            snippet = snippet[:snippet_chars].rsplit(" ", 1)[0] + "..."
        results.append(f"{i}. {title}\n   {url}\n   {snippet}")

    log.info("Tavily %r: %d results", query, len(results))
    return "\n\n".join(results) if results else "No results found."


def search_hotels(place: str, budget: str = "affordable") -> str:
    """Hotel suggestions for one place."""
    return tavily_search(f"best {budget} hotels in {place}, neighbourhood and price per night")


def search_places(country: str, month: str) -> str:
    """Research text for ranking places to visit in a country in a given month."""
    return tavily_search(f"best places to visit in {country} in {month}, must-see destinations")
