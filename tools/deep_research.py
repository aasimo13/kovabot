"""
Deep Research Tool — comprehensive multi-source research pipeline.

One tool call triggers: topic classification → query generation → parallel search
(Brave web/news + GitHub code/repos) → URL ranking → parallel fetch with code-aware
article extraction → optional code verification → LLM synthesis into a cited report.
"""

import asyncio
import json
import logging
import re
from urllib.parse import urlparse, quote

import aiohttp
from openai import AsyncOpenAI

from config import OPENAI_API_KEY, BRAVE_API_KEY

try:
    from config import GITHUB_TOKEN
except ImportError:
    GITHUB_TOKEN = ""

logger = logging.getLogger(__name__)

BRAVE_WEB_URL = "https://api.search.brave.com/res/v1/web/search"
BRAVE_NEWS_URL = "https://api.search.brave.com/res/v1/news/search"
GITHUB_API = "https://api.github.com"

DEPTH_CONFIG = {
    "quick":    {"queries": 3, "urls": 3, "news": False, "verify_code": False},
    "standard": {"queries": 5, "urls": 5, "news": True,  "verify_code": False},
    "deep":     {"queries": 8, "urls": 8, "news": True,  "verify_code": True},
}

# Domains that typically block bots or return non-article content
SKIP_DOMAINS = {
    "youtube.com", "youtu.be", "twitter.com", "x.com", "reddit.com",
    "facebook.com", "instagram.com", "tiktok.com", "linkedin.com",
    "pinterest.com", "discord.com", "t.co",
}

# Domains boosted for code/documentation research
CODE_BOOST_DOMAINS = {
    "github.com", "stackoverflow.com", "stackexchange.com",
    "docs.python.org", "developer.mozilla.org", "devdocs.io",
    "learn.microsoft.com", "docs.rs", "pkg.go.dev", "npmjs.com",
    "pypi.org", "readthedocs.io", "docs.github.com",
    "wiki.archlinux.org", "man7.org", "cppreference.com",
    "rust-lang.org", "golang.org", "typescriptlang.org",
    "react.dev", "vuejs.org", "angular.io", "svelte.dev",
    "docs.docker.com", "kubernetes.io",
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
    search_results = []

    try:
        # Step 1: Classify topic and generate queries
        is_code = await _classify_topic(client, topic)
        queries = await _generate_queries(client, topic, cfg["queries"], is_code)
        logger.info(f"Deep research: {len(queries)} queries for '{topic}' (depth={depth}, code={is_code})")

        # Step 2: Run all searches in parallel (Brave + GitHub if code topic)
        search_results = await _run_searches(queries, cfg["news"], is_code, cfg["queries"])

        if not search_results:
            return f"No search results found for: {topic}"

        # Step 3: Rank and select top URLs
        urls = _rank_and_select_urls(search_results, cfg["urls"], is_code)
        logger.info(f"Deep research: selected {len(urls)} URLs to fetch")

        # Step 4: Fetch and extract article content in parallel
        fetched = await _fetch_all(urls, cfg["urls"])
        successful = [f for f in fetched if f["content"]]
        logger.info(f"Deep research: fetched {len(successful)}/{len(urls)} pages")

        # Collect GitHub code/repo results and fetch actual file content
        code_sources = _collect_code_sources(search_results)
        if is_code and code_sources:
            code_sources = await _fetch_github_code_content(code_sources)

        # Step 5: Build sources
        sources = []
        for f in successful:
            sources.append({
                "url": f["url"],
                "title": f["title"],
                "content": f["content"],
                "type": "article",
            })
        for cs in code_sources:
            # Avoid duplicating URLs we already fetched
            if not any(s["url"] == cs["url"] for s in sources):
                sources.append(cs)

        # Fallback: if no pages fetched, use search snippets
        if not sources:
            sources = _collect_snippets(search_results, set())
            if not sources:
                return _format_search_only_report(topic, search_results)

        # Step 6: Optionally verify code snippets
        verification_notes = ""
        if is_code and cfg["verify_code"] and sources:
            verification_notes = await _verify_code_snippets(sources)

        # Step 7: Synthesize into report
        report = await _synthesize(client, topic, sources, depth, is_code, verification_notes)
        return report

    except Exception as e:
        logger.error(f"Deep research error: {e}", exc_info=True)
        try:
            if search_results:
                return _format_search_only_report(topic, search_results)
        except Exception:
            pass
        return f"Research error: {e}"


# ---------------------------------------------------------------------------
# Topic Classification
# ---------------------------------------------------------------------------

async def _classify_topic(client: AsyncOpenAI, topic: str) -> bool:
    """Determine if a topic is code/programming-related."""
    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": (
                    "Classify whether the following topic is related to programming, "
                    "software development, coding, APIs, libraries, frameworks, DevOps, "
                    "or technical documentation. Reply with only 'code' or 'general'."
                )},
                {"role": "user", "content": topic},
            ],
            max_tokens=10,
            temperature=0,
        )
        answer = response.choices[0].message.content.strip().lower()
        return "code" in answer
    except Exception as e:
        logger.debug(f"Topic classification error: {e}")
        # Fall back to keyword heuristic
        code_keywords = {
            "api", "code", "programming", "python", "javascript", "typescript",
            "rust", "golang", "java", "react", "vue", "angular", "docker",
            "kubernetes", "sql", "database", "git", "npm", "pip", "library",
            "framework", "sdk", "cli", "terminal", "bash", "linux", "debug",
            "error", "exception", "function", "class", "algorithm", "data structure",
            "regex", "http", "rest", "graphql", "websocket", "css", "html",
            "node", "deno", "bun", "webpack", "vite", "terraform", "aws",
            "azure", "gcp", "ci/cd", "deployment", "container",
        }
        topic_lower = topic.lower()
        return any(kw in topic_lower for kw in code_keywords)


# ---------------------------------------------------------------------------
# Query Generation
# ---------------------------------------------------------------------------

async def _generate_queries(client: AsyncOpenAI, topic: str, count: int, is_code: bool) -> list[str]:
    """Use gpt-4o-mini to generate diverse search queries."""
    if is_code:
        system_msg = (
            "Generate diverse search queries to thoroughly research a programming/technical topic. "
            "Include different angles:\n"
            "- Official documentation queries\n"
            "- Stack Overflow / troubleshooting queries\n"
            "- GitHub code example queries\n"
            "- Tutorial / how-to queries\n"
            "- Best practices / comparison queries\n"
            "- Recent changes / changelog queries\n"
            "Return a JSON array of strings, nothing else."
        )
    else:
        system_msg = (
            "Generate diverse web search queries to research a topic thoroughly. "
            "Include different angles: factual, recent developments, technical details, "
            "contrarian/critical views. Return a JSON array of strings, nothing else."
        )

    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": f"Topic: {topic}\nGenerate {count} search queries."},
            ],
            max_tokens=400,
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
# Search (Brave + GitHub)
# ---------------------------------------------------------------------------

async def _single_search(query: str, search_type: str = "web", count: int = 5) -> list[dict]:
    """Run a single Brave search, returns list of result dicts."""
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


async def _github_code_search(query: str, count: int = 5) -> list[dict]:
    """Search GitHub code, returns list of result dicts with code snippets."""
    if not GITHUB_TOKEN:
        return []
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    params = {"q": query, "per_page": min(count, 10)}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{GITHUB_API}/search/code", headers=headers,
                                   params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    logger.warning(f"GitHub code search HTTP {resp.status}")
                    return []
                data = await resp.json()

        results = []
        for item in data.get("items", [])[:count]:
            repo = item.get("repository", {}).get("full_name", "")
            path = item.get("path", "")
            html_url = item.get("html_url", "")
            # Build a descriptive snippet
            name = item.get("name", "")
            results.append({
                "title": f"{repo}/{path}",
                "url": html_url,
                "description": f"Code file: {name} in {repo}",
                "source_type": "github_code",
                "repo": repo,
                "path": path,
            })
        return results
    except Exception as e:
        logger.debug(f"GitHub code search error: {e}")
        return []


async def _github_repo_search(query: str, count: int = 5) -> list[dict]:
    """Search GitHub repositories, returns list of result dicts."""
    if not GITHUB_TOKEN:
        return []
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    params = {"q": query, "sort": "stars", "order": "desc", "per_page": min(count, 10)}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{GITHUB_API}/search/repositories", headers=headers,
                                   params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    logger.warning(f"GitHub repo search HTTP {resp.status}")
                    return []
                data = await resp.json()

        results = []
        for item in data.get("items", [])[:count]:
            name = item.get("full_name", "")
            desc = item.get("description", "") or ""
            stars = item.get("stargazers_count", 0)
            lang = item.get("language", "") or ""
            results.append({
                "title": f"{name} ({lang}, {stars} stars)",
                "url": item.get("html_url", ""),
                "description": desc,
                "source_type": "github_repo",
                "stars": stars,
                "language": lang,
            })
        return results
    except Exception as e:
        logger.debug(f"GitHub repo search error: {e}")
        return []


async def _github_fetch_file(repo: str, path: str) -> str:
    """Fetch raw file content from GitHub."""
    if not GITHUB_TOKEN:
        return ""
    headers = {
        "Accept": "application/vnd.github.raw+json",
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    try:
        async with aiohttp.ClientSession() as session:
            url = f"{GITHUB_API}/repos/{repo}/contents/{path}"
            async with session.get(url, headers=headers,
                                   timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    return ""
                text = await resp.text()
                return text[:8000]
    except Exception as e:
        logger.debug(f"GitHub file fetch error: {e}")
        return ""


async def _run_searches(queries: list[str], include_news: bool, is_code: bool, query_count: int) -> list[dict]:
    """Run all queries in parallel (Brave web/news + GitHub code/repos if code topic)."""
    tasks = []
    for q in queries:
        tasks.append(_single_search(q, "web", 5))
        if include_news:
            tasks.append(_single_search(q, "news", 3))

    # Add GitHub searches for code topics
    if is_code and GITHUB_TOKEN:
        # Use first 2-3 queries for GitHub code search
        code_query_count = min(3, len(queries))
        for q in queries[:code_query_count]:
            tasks.append(_github_code_search(q, 3))
        # One repo search with the main topic
        tasks.append(_github_repo_search(queries[0], 5))

    all_results = await asyncio.gather(*tasks, return_exceptions=True)
    combined = []
    for result in all_results:
        if isinstance(result, list):
            combined.extend(result)
    return combined


# ---------------------------------------------------------------------------
# URL Ranking
# ---------------------------------------------------------------------------

def _rank_and_select_urls(search_results: list[dict], max_urls: int, is_code: bool) -> list[dict]:
    """Score, deduplicate, and select top URLs."""
    seen_urls = set()
    seen_domains = set()
    scored = []

    for r in search_results:
        url = r.get("url", "")
        # Skip GitHub code/repo results — they're handled as direct sources
        if r.get("source_type") in ("github_code", "github_repo"):
            continue
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
        # Boost code/documentation domains for code topics
        if is_code and any(cd in domain for cd in CODE_BOOST_DOMAINS):
            score += 8

        scored.append({"url": url, "title": r.get("title", ""), "score": score,
                        "description": r.get("description", "")})

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:max_urls]


# ---------------------------------------------------------------------------
# Article Extraction (Code-Aware)
# ---------------------------------------------------------------------------

def _preserve_code_blocks(html: str) -> tuple[str, list[str]]:
    """Extract <pre>/<code> blocks, replace with placeholders, return (html, blocks)."""
    blocks = []
    counter = [0]

    def _replace_pre(match):
        content = match.group(1)
        # Try to detect language from class attribute
        lang_match = re.search(r'class="[^"]*(?:language-|lang-)(\w+)', match.group(0))
        lang = lang_match.group(1) if lang_match else ""
        # Strip inner tags
        code_text = re.sub(r"<[^>]+>", "", content)
        code_text = code_text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
        code_text = code_text.replace("&quot;", '"').replace("&#39;", "'")
        placeholder = f"__CODE_BLOCK_{counter[0]}__"
        blocks.append(f"```{lang}\n{code_text.strip()}\n```")
        counter[0] += 1
        return placeholder

    # Match <pre>...</pre> (may contain <code> inside)
    html = re.sub(r"<pre[^>]*>(.*?)</pre>", _replace_pre, html, flags=re.DOTALL | re.IGNORECASE)

    return html, blocks


def _restore_code_blocks(text: str, blocks: list[str]) -> str:
    """Put code blocks back into text."""
    for i, block in enumerate(blocks):
        text = text.replace(f"__CODE_BLOCK_{i}__", f"\n{block}\n")
    return text


def _extract_article(html: str) -> str:
    """Extract article content from HTML using cascading heuristics, preserving code blocks."""
    # Strip unwanted elements first
    for tag in ["script", "style", "nav", "footer", "header", "aside", "noscript"]:
        html = re.sub(rf"<{tag}[^>]*>.*?</{tag}>", "", html, flags=re.DOTALL | re.IGNORECASE)

    # Preserve code blocks before stripping tags
    html, code_blocks = _preserve_code_blocks(html)

    # Try 1: <article> tag
    article_match = re.search(r"<article[^>]*>(.*?)</article>", html, re.DOTALL | re.IGNORECASE)
    if article_match:
        text = _tags_to_text(article_match.group(1))
        if len(text) > 200:
            return _restore_code_blocks(text[:8000], code_blocks)

    # Try 2: <main> tag
    main_match = re.search(r"<main[^>]*>(.*?)</main>", html, re.DOTALL | re.IGNORECASE)
    if main_match:
        text = _tags_to_text(main_match.group(1))
        if len(text) > 200:
            return _restore_code_blocks(text[:8000], code_blocks)

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
            return _restore_code_blocks(text[:8000], code_blocks)

    # Try 4: Just grab all <p> tags
    paragraphs = re.findall(r"<p[^>]*>(.*?)</p>", html, re.DOTALL | re.IGNORECASE)
    if paragraphs:
        text = "\n\n".join(_tags_to_text(p) for p in paragraphs)
        if len(text) > 100:
            return _restore_code_blocks(text[:8000], code_blocks)

    # Try 5: Full text strip
    text = _tags_to_text(html)
    return _restore_code_blocks(text[:8000], code_blocks) if text else ""


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
# GitHub Source Collection
# ---------------------------------------------------------------------------

def _collect_code_sources(search_results: list[dict]) -> list[dict]:
    """Build source entries from GitHub code/repo search results."""
    sources = []
    seen = set()

    # Collect repo results first (higher value context)
    for r in search_results:
        if r.get("source_type") != "github_repo":
            continue
        url = r.get("url", "")
        if url in seen:
            continue
        seen.add(url)
        sources.append({
            "url": url,
            "title": r.get("title", ""),
            "content": r.get("description", ""),
            "type": "github_repo",
        })

    # Then code results
    for r in search_results:
        if r.get("source_type") != "github_code":
            continue
        url = r.get("url", "")
        if url in seen:
            continue
        seen.add(url)
        sources.append({
            "url": url,
            "title": r.get("title", ""),
            "content": r.get("description", ""),
            "type": "github_code",
            "repo": r.get("repo", ""),
            "path": r.get("path", ""),
        })

    return sources[:6]  # Cap to avoid overwhelming synthesis


async def _fetch_github_code_content(code_sources: list[dict]) -> list[dict]:
    """Fetch actual file content for GitHub code search results."""
    if not GITHUB_TOKEN:
        return code_sources

    sem = asyncio.Semaphore(3)
    enriched = []

    async def _fetch_one(src):
        async with sem:
            if src.get("type") == "github_code" and src.get("repo") and src.get("path"):
                content = await _github_fetch_file(src["repo"], src["path"])
                if content:
                    src = dict(src)
                    src["content"] = f"```\n{content}\n```"
            enriched.append(src)

    await asyncio.gather(*[_fetch_one(s) for s in code_sources], return_exceptions=True)
    return enriched


# ---------------------------------------------------------------------------
# Code Verification
# ---------------------------------------------------------------------------

async def _verify_code_snippets(sources: list[dict]) -> str:
    """Extract Python code blocks from sources and test them in the sandbox."""
    try:
        from tools.code_exec import run_sandboxed
    except ImportError:
        return ""

    # Extract Python code blocks
    python_blocks = []
    for src in sources:
        content = src.get("content", "")
        # Match ```python ... ``` blocks
        for match in re.finditer(r"```(?:python|py)?\n(.*?)```", content, re.DOTALL):
            code = match.group(1).strip()
            if len(code) > 50 and len(code) < 2000:  # Skip trivial or huge blocks
                python_blocks.append((code, src.get("title", "")))
            if len(python_blocks) >= 3:
                break
        if len(python_blocks) >= 3:
            break

    if not python_blocks:
        return ""

    results = []
    loop = asyncio.get_event_loop()
    for code, source_title in python_blocks[:3]:
        try:
            output = await asyncio.wait_for(
                loop.run_in_executor(None, run_sandboxed, code),
                timeout=10,
            )
            status = "runs" if "Error" not in output and "error" not in output.lower() else "has errors"
            results.append(f"- Code from '{source_title}': {status}")
            if status == "runs" and output and output != "(no output)":
                results.append(f"  Output: {output[:200]}")
        except Exception:
            results.append(f"- Code from '{source_title}': could not verify (timeout or sandbox error)")

    if results:
        return "Code verification results:\n" + "\n".join(results)
    return ""


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
            "type": r.get("source_type", "web"),
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

async def _synthesize(client: AsyncOpenAI, topic: str, sources: list[dict],
                      depth: str, is_code: bool, verification_notes: str = "") -> str:
    """Use gpt-4o-mini to synthesize sources into a structured report."""
    # Build source context
    source_blocks = []
    for i, src in enumerate(sources, 1):
        src_type = src.get("type", "article")
        label = {"github_code": "GitHub Code", "github_repo": "GitHub Repo",
                 "article": "Article", "web": "Web", "news": "News"}.get(src_type, "Source")
        block = f"[Source {i}] ({label}) {src['title']}\nURL: {src['url']}\n{src['content'][:4000]}"
        source_blocks.append(block)

    source_text = "\n\n---\n\n".join(source_blocks)

    detail_level = {
        "quick": "Provide a concise summary (3-5 paragraphs).",
        "standard": "Provide a thorough analysis with multiple sections.",
        "deep": "Provide a comprehensive, detailed report with extensive analysis.",
    }.get(depth, "Provide a thorough analysis.")

    if is_code:
        system_prompt = (
            "You are a senior software engineer and technical researcher. Synthesize the provided "
            "sources into a well-structured technical report with markdown formatting. Include:\n"
            "- Clear section headers (##)\n"
            "- Inline citations as [Source N] referencing the source number\n"
            "- A 'Key Findings' section at the top\n"
            "- Code examples in fenced code blocks with language tags where relevant\n"
            "- API signatures, usage patterns, and practical implementation details\n"
            "- Note any version-specific caveats, breaking changes, or deprecations\n"
            "- Mention relevant GitHub repos with star counts when applicable\n"
            "- Note any contradictions or differing approaches between sources\n"
            "- A 'Sources' section at the end listing all sources with their URLs\n\n"
            f"{detail_level}\n"
            "Write in a clear, technical style. Include working code examples when sources provide them. "
            "Do not make up information — only use what's in the sources."
        )
    else:
        system_prompt = (
            "You are a research analyst. Synthesize the provided sources into a well-structured "
            "report with markdown formatting. Include:\n"
            "- Clear section headers (##)\n"
            "- Inline citations as [Source N] referencing the source number\n"
            "- A 'Key Findings' section at the top\n"
            "- Note any contradictions between sources\n"
            "- A 'Sources' section at the end listing all sources with their URLs\n\n"
            f"{detail_level}\n"
            "Write in a clear, informative style. Do not make up information — only use what's in the sources."
        )

    user_content = f"Research topic: {topic}\n\n{source_text}"
    if verification_notes:
        user_content += f"\n\n---\n\n{verification_notes}"

    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            max_tokens=3000,
            temperature=0.3,
        )
        report = response.choices[0].message.content.strip()
        return report
    except Exception as e:
        logger.error(f"Synthesis error: {e}")
        lines = [f"# Research: {topic}\n"]
        for i, src in enumerate(sources, 1):
            lines.append(f"## Source {i}: {src['title']}")
            lines.append(src["content"][:2000])
            lines.append(f"\n*Source: {src['url']}*\n")
        return "\n".join(lines)
