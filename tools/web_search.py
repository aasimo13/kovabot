import aiohttp
import logging

from config import BRAVE_API_KEY

logger = logging.getLogger(__name__)

BRAVE_WEB_URL = "https://api.search.brave.com/res/v1/web/search"
BRAVE_NEWS_URL = "https://api.search.brave.com/res/v1/news/search"


async def brave_search(query: str, count: int = 5, search_type: str = "web") -> str:
    """Search the web or news using Brave Search API.

    search_type: "web" for general search, "news" for news articles/headlines.
    """
    if not BRAVE_API_KEY:
        return "Error: BRAVE_API_KEY not configured."

    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "X-Subscription-Token": BRAVE_API_KEY,
    }
    params = {"q": query, "count": min(count, 20)}

    try:
        if search_type == "news":
            return await _search_news(headers, params, count)
        else:
            return await _search_web(headers, params, count)
    except Exception as e:
        logger.error(f"Brave search error: {e}")
        return f"Search error: {e}"


async def _search_web(headers: dict, params: dict, count: int) -> str:
    async with aiohttp.ClientSession() as session:
        async with session.get(BRAVE_WEB_URL, headers=headers, params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                return f"Search API error: HTTP {resp.status}"
            data = await resp.json()

    results = []
    for item in data.get("web", {}).get("results", [])[:count]:
        results.append(f"**{item['title']}**\n{item.get('description', '')}\n{item['url']}")

    if not results:
        return "No search results found."

    return "\n\n".join(results)


async def _search_news(headers: dict, params: dict, count: int) -> str:
    async with aiohttp.ClientSession() as session:
        async with session.get(BRAVE_NEWS_URL, headers=headers, params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                return f"News search API error: HTTP {resp.status}"
            data = await resp.json()

    results = []
    for item in data.get("results", [])[:count]:
        title = item.get("title", "Untitled")
        desc = item.get("description", "")
        url = item.get("url", "")
        source = item.get("meta_url", {}).get("hostname", "") if isinstance(item.get("meta_url"), dict) else ""
        age = item.get("age", "")

        line = f"**{title}**"
        if source:
            line += f" ({source})"
        if age:
            line += f" — {age}"
        if desc:
            line += f"\n{desc}"
        if url:
            line += f"\n{url}"
        results.append(line)

    if not results:
        return "No news results found."

    return "\n\n".join(results)
