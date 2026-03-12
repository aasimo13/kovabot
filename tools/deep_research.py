"""
Deep Research Tool — comprehensive multi-source research pipeline.

One tool call triggers: query generation → parallel search → URL ranking →
parallel fetch with article extraction → LLM synthesis into a cited report.
"""

import asyncio
import json
import logging
import re
from urllib.parse import urlparse

import aiohttp
from openai import AsyncOpenAI

from config import OPENAI_API_KEY, BRAVE_API_KEY

logger = logging.getLogger(__name__)

BRAVE_WEB_URL = "https://api.search.brave.com/res/v1/web/search"
BRAVE_NEWS_URL = "https://api.search.brave.com/res/v1/news/search"

DEPTH_CONFIG = {
    "quick":    {"queries": 3, "urls": 3, "news": False},
    "standard": {"queries": 5, "urls": 5, "news": True},
    "deep":     {"queries": 8, "urls": 8, "news": True},
}

# Domains that typically block bots or return non-article content
SKIP_DOMAINS = {
    "youtube.com", "youtu.be", "twitter.com", "x.com", "reddit.com",
    "facebook.com", "instagram.com", "tiktok.com", "linkedin.com",
    "pinterest.com", "discord.com", "t.co",
}

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


async def deep_research(topic: str, depth: str = "standard", chat_id: int = 0) -> str:
    """Perform comprehensive multi-source research on a topic."""
    if not OPENAI_API_KEY:
        return "Error: OPENAI_API_KEY not configured."
    if not BRAVE_API_KEY:
        return "Error: BRAVE_API_KEY not configured."

    depth = depth if depth in DEPTH_CONFIG else "standard"
    cfg = DEPTH_CONFIG[depth]
    client = AsyncOpenAI(api_key=OPENAI_API_KEY)

    try:
        # Step 1: Generate diverse search queries
        queries = await _generate_queries(client, topic, cfg["queries"])
        logger.info(f"Deep research: {len(queries)} queries for '{topic}' (depth={depth})")

        # Step 2: Run all searches in parallel
        search_results = await _run_searches(queries, cfg["news"])

        if not search_results:
            return f"No search results found for: {topic}"

        # Step 3: Rank and select top URLs
        urls = _rank_and_select_urls(search_results, cfg["urls"])
        logger.info(f"Deep research: selected {len(urls)} URLs to fetch")

        # Step 4: Fetch and extract article content in parallel
        fetched = await _fetch_all(urls, cfg["urls"])
        successful = [f for f in fetched if f["content"]]
        logger.info(f"Deep research: fetched {len(successful)}/{len(urls)} pages")

        # Step 5: Build sources and synthesize
        sources = []
        for f in successful:
            sources.append({
                "url": f["url"],
                "title": f["title"],
                "content": f["content"],
            })

        # Fallback: if no pages fetched, use search snippets
        if not sources:
            sources = _collect_snippets(search_results, set())
            if not sources:
                return _format_search_only_report(topic, search_results)

        # Step 6: Synthesize into report
        report = await _synthesize(client, topic, sources, depth)
        return report

    except Exception as e:
        logger.error(f"Deep research error: {e}", exc_info=True)
        # Last resort: return formatted search results
        try:
            if search_results:
                return _format_search_only_report(topic, search_results)
        except Exception:
            pass
        return f"Research error: {e}"


# ---------------------------------------------------------------------------
# Query Generation
# ---------------------------------------------------------------------------

async def _generate_queries(client: AsyncOpenAI, topic: str, count: int) -> list[str]:
    """Use gpt-4o-mini to generate diverse search queries."""
    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": (
                    "Generate diverse web search queries to research a topic thoroughly. "
                    "Include different angles: factual, recent developments, technical details, "
                    "contrarian/critical views. Return a JSON array of strings, nothing else."
                )},
                {"role": "user", "content": f"Topic: {topic}\nGenerate {count} search queries."},
            ],
            max_tokens=300,
            temperature=0.7,
        )
        text = response.choices[0].message.content.strip()
        # Try JSON parse first
        try:
            queries = json.loads(text)
            if isinstance(queries, list) and all(isinstance(q, str) for q in queries):
                return queries[:count]
        except json.JSONDecodeError:
            pass
        # Fallback: split by newlines, strip numbering
        lines = [re.sub(r"^\d+[\.\)]\s*", "", line.strip().strip('"')) for line in text.split("\n") if line.strip()]
        return lines[:count] if lines else [topic]
    except Exception as e:
        logger.error(f"Query generation error: {e}")
        return [topic]


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

async def _single_search(query: str, search_type: str = "web", count: int = 5) -> list[dict]:
    """Run a single Brave search, returns list of {title, url, description, source_type}."""
    url = BRAVE_NEWS_URL if search_type == "news" else BRAVE_WEB_URL
    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "X-Subscription-Token": BRAVE_API_KEY,
    }
    params = {"q": query, "count": min(count, 20)}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, params=params,
                                   timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    logger.warning(f"Brave {search_type} search HTTP {resp.status} for: {query}")
                    return []
                data = await resp.json()

        results = []
        if search_type == "news":
            for item in data.get("results", [])[:count]:
                results.append({
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "description": item.get("description", ""),
                    "source_type": "news",
                })
        else:
            for item in data.get("web", {}).get("results", [])[:count]:
                results.append({
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "description": item.get("description", ""),
                    "source_type": "web",
                })
        return results
    except Exception as e:
        logger.error(f"Search error ({search_type}): {e}")
        return []


async def _run_searches(queries: list[str], include_news: bool) -> list[dict]:
    """Run all queries in parallel (web + optionally news)."""
    tasks = []
    for q in queries:
        tasks.append(_single_search(q, "web", 5))
        if include_news:
            tasks.append(_single_search(q, "news", 3))

    all_results = await asyncio.gather(*tasks, return_exceptions=True)
    combined = []
    for result in all_results:
        if isinstance(result, list):
            combined.extend(result)
    return combined


# ---------------------------------------------------------------------------
# URL Ranking
# ---------------------------------------------------------------------------

def _rank_and_select_urls(search_results: list[dict], max_urls: int) -> list[dict]:
    """Score, deduplicate, and select top URLs."""
    seen_urls = set()
    seen_domains = set()
    scored = []

    for r in search_results:
        url = r.get("url", "")
        if not url or url in seen_urls:
            continue

        domain = urlparse(url).netloc.lower().replace("www.", "")
        if any(skip in domain for skip in SKIP_DOMAINS):
            continue

        seen_urls.add(url)

        score = 0
        # Prefer unique domains for diversity
        if domain not in seen_domains:
            score += 10
            seen_domains.add(domain)
        # Prefer web results over news (typically more substantive)
        if r.get("source_type") == "web":
            score += 5
        # Prefer results with descriptions
        if r.get("description"):
            score += 2

        scored.append({"url": url, "title": r.get("title", ""), "score": score,
                        "description": r.get("description", "")})

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:max_urls]


# ---------------------------------------------------------------------------
# Article Extraction
# ---------------------------------------------------------------------------

def _extract_article(html: str) -> str:
    """Extract article content from HTML using cascading heuristics."""
    # Strip unwanted elements first
    for tag in ["script", "style", "nav", "footer", "header", "aside", "noscript"]:
        html = re.sub(rf"<{tag}[^>]*>.*?</{tag}>", "", html, flags=re.DOTALL | re.IGNORECASE)

    # Try 1: <article> tag
    article_match = re.search(r"<article[^>]*>(.*?)</article>", html, re.DOTALL | re.IGNORECASE)
    if article_match:
        text = _tags_to_text(article_match.group(1))
        if len(text) > 200:
            return text[:8000]

    # Try 2: <main> tag
    main_match = re.search(r"<main[^>]*>(.*?)</main>", html, re.DOTALL | re.IGNORECASE)
    if main_match:
        text = _tags_to_text(main_match.group(1))
        if len(text) > 200:
            return text[:8000]

    # Try 3: Find div with highest paragraph density
    divs = re.findall(r"<div[^>]*>(.*?)</div>", html, re.DOTALL | re.IGNORECASE)
    best_div = ""
    best_p_count = 0
    for div_content in divs:
        p_count = len(re.findall(r"<p[^>]*>", div_content, re.IGNORECASE))
        if p_count > best_p_count:
            best_p_count = p_count
            best_div = div_content
    if best_p_count >= 3:
        text = _tags_to_text(best_div)
        if len(text) > 200:
            return text[:8000]

    # Try 4: Just grab all <p> tags
    paragraphs = re.findall(r"<p[^>]*>(.*?)</p>", html, re.DOTALL | re.IGNORECASE)
    if paragraphs:
        text = "\n\n".join(_tags_to_text(p) for p in paragraphs)
        if len(text) > 100:
            return text[:8000]

    # Try 5: Full text strip
    text = _tags_to_text(html)
    return text[:8000] if text else ""


def _tags_to_text(html: str) -> str:
    """Convert HTML fragment to plain text."""
    text = re.sub(r"<(br|hr)[^>]*>", "\n", html, flags=re.IGNORECASE)
    text = re.sub(r"</(p|div|h[1-6]|tr|li)>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<li[^>]*>", "- ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " ")
    lines = []
    for line in text.split("\n"):
        line = " ".join(line.split())
        if line:
            lines.append(line)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# URL Fetching
# ---------------------------------------------------------------------------

async def _fetch_and_extract(session: aiohttp.ClientSession, url: str) -> dict:
    """Fetch a single URL and extract article content."""
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15),
                               allow_redirects=True) as resp:
            if resp.status != 200:
                return {"url": url, "title": "", "content": ""}
            content_type = resp.headers.get("Content-Type", "")
            if "text/html" not in content_type and "text/plain" not in content_type:
                return {"url": url, "title": "", "content": ""}
            html = await resp.text(errors="replace")

        # Extract title
        title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.DOTALL | re.IGNORECASE)
        title = _tags_to_text(title_match.group(1)).strip() if title_match else ""

        content = _extract_article(html)
        return {"url": url, "title": title, "content": content}
    except Exception as e:
        logger.debug(f"Fetch error for {url}: {e}")
        return {"url": url, "title": "", "content": ""}


async def _fetch_all(ranked_urls: list[dict], max_urls: int) -> list[dict]:
    """Fetch all URLs in parallel with a concurrency semaphore."""
    sem = asyncio.Semaphore(5)
    headers = {"User-Agent": USER_AGENT}

    async def _limited_fetch(session, url_info):
        async with sem:
            result = await _fetch_and_extract(session, url_info["url"])
            # Use search result title as fallback
            if not result["title"] and url_info.get("title"):
                result["title"] = url_info["title"]
            return result

    async with aiohttp.ClientSession(headers=headers) as session:
        tasks = [_limited_fetch(session, u) for u in ranked_urls[:max_urls]]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    fetched = []
    for r in results:
        if isinstance(r, dict):
            fetched.append(r)
    return fetched


# ---------------------------------------------------------------------------
# Fallback Helpers
# ---------------------------------------------------------------------------

def _collect_snippets(search_results: list[dict], fetched_urls: set) -> list[dict]:
    """Use search result snippets as fallback sources."""
    sources = []
    seen = set()
    for r in search_results:
        url = r.get("url", "")
        if url in seen or url in fetched_urls or not r.get("description"):
            continue
        seen.add(url)
        sources.append({
            "url": url,
            "title": r.get("title", ""),
            "content": r.get("description", ""),
        })
        if len(sources) >= 8:
            break
    return sources


def _format_search_only_report(topic: str, results: list[dict]) -> str:
    """Last resort: format raw search results as a report."""
    lines = [f"# Research: {topic}\n", "*Could not fetch full articles. Here are the search results:*\n"]
    seen = set()
    for r in results:
        url = r.get("url", "")
        if url in seen:
            continue
        seen.add(url)
        lines.append(f"**{r.get('title', 'Untitled')}**")
        if r.get("description"):
            lines.append(r["description"])
        lines.append(f"[Link]({url})\n")
        if len(seen) >= 10:
            break
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Synthesis
# ---------------------------------------------------------------------------

async def _synthesize(client: AsyncOpenAI, topic: str, sources: list[dict], depth: str) -> str:
    """Use gpt-4o-mini to synthesize sources into a structured report."""
    # Build source context
    source_blocks = []
    for i, src in enumerate(sources, 1):
        block = f"[Source {i}] {src['title']}\nURL: {src['url']}\n{src['content'][:4000]}"
        source_blocks.append(block)

    source_text = "\n\n---\n\n".join(source_blocks)

    detail_level = {
        "quick": "Provide a concise summary (3-5 paragraphs).",
        "standard": "Provide a thorough analysis with multiple sections.",
        "deep": "Provide a comprehensive, detailed report with extensive analysis.",
    }.get(depth, "Provide a thorough analysis.")

    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": (
                    "You are a research analyst. Synthesize the provided sources into a well-structured "
                    "report with markdown formatting. Include:\n"
                    "- Clear section headers (##)\n"
                    "- Inline citations as [Source N] referencing the source number\n"
                    "- A 'Key Findings' section at the top\n"
                    "- Note any contradictions between sources\n"
                    "- A 'Sources' section at the end listing all sources with their URLs\n\n"
                    f"{detail_level}\n"
                    "Write in a clear, informative style. Do not make up information — only use what's in the sources."
                )},
                {"role": "user", "content": f"Research topic: {topic}\n\n{source_text}"},
            ],
            max_tokens=3000,
            temperature=0.3,
        )
        report = response.choices[0].message.content.strip()
        return report
    except Exception as e:
        logger.error(f"Synthesis error: {e}")
        # Fallback: manual formatting
        lines = [f"# Research: {topic}\n"]
        for i, src in enumerate(sources, 1):
            lines.append(f"## Source {i}: {src['title']}")
            lines.append(src["content"][:2000])
            lines.append(f"\n*Source: {src['url']}*\n")
        return "\n".join(lines)
