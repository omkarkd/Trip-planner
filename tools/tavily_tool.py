import tavily
import os   
from dotenv import load_dotenv

load_dotenv()

client = tavily.TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))

def tavily_search(query: str):

    
    response = client.search(
        query = query,max_results=5
    )    
    results = []

    for i,r in enumerate(response['results'], start=1):
        title = r.get("title","Unknown")
        url = r.get("url","")
        snippet = r.get('content').strip()

        if len(snippet) > 300:
            snippet = snippet[:300].rsplit(' ', 1)[0] + "..."

        results.append(f"{i}. ***{title}*** \n {url}\n {snippet}\n ")
    return "\n\n".join(results)