### Tavily tool
from tavily import TavilyClient
import os
from pathlib import Path
from dotenv import load_dotenv

# this file is in tools/, so .env is one level up
env_path = Path(__file__).resolve().parent.parent / ".env"
print("Loading:", env_path, "exists:", env_path.exists())

load_dotenv(env_path, override=True)

api_key = os.getenv("TAVILY_API_KEY")
print("Key loaded:", bool(api_key))

client = TavilyClient(
    api_key= os.getenv("TAVILY_API_KEY")
)
print(client)

def tavily_search(query):
    response = client.search(
        query= query,
        max_results= 5
    )

    results = []

    for i, r in enumerate(response["results"], 1):
        title   = r.get("title", "Unknown")
        url     = r.get("url", "")
        snippet = r.get("content", "").strip()
        # Keep only the first 300 characters to avoid wall-of-text
        if len(snippet) > 300:
            snippet = snippet[:300].rsplit(" ", 1)[0] + "..."

        results.append(f"{i}. **{title}**\n   {url}\n   {snippet}")

    return "\n\n".join(results)
