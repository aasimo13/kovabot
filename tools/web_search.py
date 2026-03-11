import aiohttp
import logging

from config import BRAVE_API_KEY

logger = logging.getLogger(__name__)

BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"


async def brave_search(query: str, count: int = 5) -> str:
    if not BRAVE_API_KEY:
        return "Error: BRAVE_API_KEY not configured."

    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "X-Subscription-Token": BRAVE_API_KEY,
    }
    params = {"q": query, "count": min(count, 10)}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(BRAVE_SEARCH_URL, headers=headers, params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    return f"Search API error: HTTP {resp.status}"
                data = await resp.json()

        results = []
        for item in data.get("web", {}).get("results", [])[:count]:
            results.append(f"**{item['title']}**\n{item.get('description', '')}\n{item['url']}")

        if not results:
            return "No search results found."

        return "\n\n".join(results)

    except Exception as e:
        logger.error(f"Brave search error: {e}")
        return f"Search error: {e}"
