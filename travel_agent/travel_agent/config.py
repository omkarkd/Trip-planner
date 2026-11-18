"""
Central configuration. Loads .env once, sets up logging, and exposes settings.

Place .env in your project root (e.g. /Users/omkar/Documents/supplychain/.env):

    OLLAMA_BASE_URL=https://193-123-179-35.sslip.io
    OLLAMA_API_KEY=...
    OAG_FLIGHT_API_KEY=...
    TAVILY_API_KEY=...
    # optional
    DEFAULT_ORIGIN=LGW
    EXTRACT_MODEL=qwen2.5:1.5b
    ITINERARY_MODEL=llama3.2
    LOG_LEVEL=INFO
"""

import logging
import os
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

# Look for .env from the current working directory upwards, else the project root
# (two levels above this file: <root>/travel_agent/config.py -> <root>/.env).
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = find_dotenv(usecwd=True) or str(_PROJECT_ROOT / ".env")
load_dotenv(ENV_FILE, override=True)

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("travel_agent.config")


def require(name: str) -> str:
    """Return an env var or raise a clear error saying which file was checked."""
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing environment variable {name!r} (looked in {ENV_FILE})")
    return value


# --- LLM (Ollama on Oracle, or local) ---------------------------------------
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY")          # None for a local Ollama
OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "600"))
EXTRACT_MODEL = os.getenv("EXTRACT_MODEL", "qwen2.5:1.5b")
ITINERARY_MODEL = os.getenv("ITINERARY_MODEL", "llama3.2")

# --- External APIs -----------------------------------------------------------
OAG_FLIGHT_API_KEY = os.getenv("OAG_FLIGHT_API_KEY")
OAG_BASE_URL = os.getenv("OAG_BASE_URL", "https://api.oag.com")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")

# --- App defaults ------------------------------------------------------------
DEFAULT_ORIGIN = os.getenv("DEFAULT_ORIGIN", "LGW").upper()
DEFAULT_TRIP_DAYS = int(os.getenv("DEFAULT_TRIP_DAYS", "5"))
DEFAULT_DAYS_AHEAD = int(os.getenv("DEFAULT_DAYS_AHEAD", "7"))

# --- Cache -------------------------------------------------------------------
CACHE_DIR = Path(os.getenv("CACHE_DIR", str(Path(ENV_FILE).parent / ".cache")))
FLIGHT_CACHE_TTL = int(os.getenv("FLIGHT_CACHE_TTL", str(6 * 3600)))    # 6 hours
SEARCH_CACHE_TTL = int(os.getenv("SEARCH_CACHE_TTL", str(24 * 3600)))   # 24 hours

log.debug("Loaded config from %s (Ollama: %s)", ENV_FILE, OLLAMA_BASE_URL)
