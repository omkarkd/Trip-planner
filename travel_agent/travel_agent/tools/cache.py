"""
Tiny file-based cache with a time-to-live, to save API quota (OAG, Tavily).

    @cached(ttl_seconds=6 * 3600, cache_if=lambda r: not r.get("error"))
    def search_oag(...): ...

Results are stored as JSON in CACHE_DIR/<function name>/<hash>.json.
Return values must be JSON-serialisable (dicts, lists, strings, numbers).
"""

import functools
import hashlib
import json
import logging
import shutil
import time
from pathlib import Path
from typing import Any, Callable

from .. import config

log = logging.getLogger("travel_agent.cache")


def _key(args: tuple, kwargs: dict) -> str:
    raw = json.dumps([args, kwargs], sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def cached(
    ttl_seconds: int,
    namespace: str | None = None,
    cache_if: Callable[[Any], bool] = lambda value: value is not None,
):
    """Cache a function's result on disk for ttl_seconds. Failed results can be skipped via cache_if."""

    def decorator(fn):
        ns = namespace or fn.__name__

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            path: Path = config.CACHE_DIR / ns / f"{_key(args, kwargs)}.json"

            if path.exists():
                try:
                    entry = json.loads(path.read_text())
                    if time.time() - entry["ts"] < ttl_seconds:
                        log.info("cache hit  %s%s", ns, args)
                        return entry["value"]
                except (json.JSONDecodeError, KeyError, OSError):
                    pass  # corrupt entry: recompute

            value = fn(*args, **kwargs)

            if cache_if(value):
                try:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(json.dumps({"ts": time.time(), "value": value}, default=str))
                except (TypeError, OSError) as exc:
                    log.warning("could not cache %s: %s", ns, exc)
            return value

        wrapper.cache_namespace = ns
        return wrapper

    return decorator


def clear_cache(namespace: str | None = None) -> None:
    """Delete one namespace (e.g. 'search_oag') or the whole cache."""
    target = config.CACHE_DIR / namespace if namespace else config.CACHE_DIR
    if target.exists():
        shutil.rmtree(target)
        log.info("cleared cache %s", target)
