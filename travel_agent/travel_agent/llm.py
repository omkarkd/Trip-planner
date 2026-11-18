"""
LLM factory. Every model goes through make_llm(), so switching between local
Ollama, Oracle Ollama (with API key) or another endpoint is a .env change only.

    from travel_agent.llm import get_extract_llm, get_itinerary_llm
    extract_llm = get_extract_llm()      # qwen2.5:1.5b, temperature 0
    llm = get_itinerary_llm()            # llama3.2, capped output
"""

from functools import lru_cache

from langchain_ollama import ChatOllama

from . import config


def make_llm(model: str, **kwargs) -> ChatOllama:
    """Create a ChatOllama client pointing at OLLAMA_BASE_URL, adding the API key if set."""
    headers = {}
    if config.OLLAMA_API_KEY:
        headers["Authorization"] = f"Bearer {config.OLLAMA_API_KEY}"
    return ChatOllama(
        model=model,
        base_url=config.OLLAMA_BASE_URL,
        client_kwargs={"headers": headers, "timeout": config.OLLAMA_TIMEOUT},
        **kwargs,
    )


@lru_cache(maxsize=1)
def get_extract_llm() -> ChatOllama:
    """Small, fast model for structured extraction."""
    return make_llm(config.EXTRACT_MODEL, temperature=0)


@lru_cache(maxsize=1)
def get_itinerary_llm() -> ChatOllama:
    """Larger model for planning and writing."""
    return make_llm(config.ITINERARY_MODEL, num_predict=700)


def ping() -> str:
    """Quick connectivity check: returns the model's one-word reply."""
    return get_extract_llm().invoke("Reply with one word: hello").content
