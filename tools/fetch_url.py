import aiohttp
import logging
import re

logger = logging.getLogger(__name__)

MAX_CONTENT_LENGTH = 15000


async def fetch_url(url: str) -> str:
    """Fetch a URL and return its text content, cleaned of HTML tags."""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; KovaBot/1.0)",
        }
        timeout = aiohttp.ClientTimeout(total=20)

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=timeout, allow_redirects=True) as resp:
                if resp.status != 200:
                    return f"Error: HTTP {resp.status} fetching {url}"

                content_type = resp.headers.get("Content-Type", "")
                if "text/html" in content_type or "text/plain" in content_type:
                    html = await resp.text(errors="replace")
                else:
                    return f"Cannot read this content type: {content_type}"

        # Basic HTML to text conversion
        text = _html_to_text(html)

        if len(text) > MAX_CONTENT_LENGTH:
            text = text[:MAX_CONTENT_LENGTH] + "\n...(truncated)"

        if not text.strip():
            return "The page appears to be empty or JavaScript-only."

        return text

    except aiohttp.ClientError as e:
        logger.error(f"URL fetch error: {e}")
        return f"Error fetching URL: {e}"
    except Exception as e:
        logger.error(f"URL fetch error: {e}")
        return f"Error: {e}"


def _html_to_text(html: str) -> str:
    """Rough HTML-to-text conversion. Strips tags, decodes entities."""
    # Remove script and style blocks
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)

    # Convert common block elements to newlines
    html = re.sub(r"<(br|hr|/p|/div|/h[1-6]|/tr|/li)[^>]*>", "\n", html, flags=re.IGNORECASE)
    html = re.sub(r"<li[^>]*>", "\n- ", html, flags=re.IGNORECASE)

    # Strip remaining tags
    html = re.sub(r"<[^>]+>", "", html)

    # Decode common HTML entities
    html = html.replace("&amp;", "&")
    html = html.replace("&lt;", "<")
    html = html.replace("&gt;", ">")
    html = html.replace("&quot;", '"')
    html = html.replace("&#39;", "'")
    html = html.replace("&nbsp;", " ")

    # Collapse whitespace
    lines = []
    for line in html.split("\n"):
        line = " ".join(line.split())
        if line:
            lines.append(line)

    return "\n".join(lines)
