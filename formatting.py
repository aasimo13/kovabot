import re
import html


def markdown_to_telegram_html(text: str) -> str:
    """Convert common Markdown patterns to Telegram-compatible HTML.

    Handles: bold, italic, code blocks, inline code, links, headers.
    Falls back gracefully — if conversion produces broken HTML, callers
    should catch the Telegram error and resend as plain text.
    """
    # Escape HTML entities first (but preserve any intentional HTML)
    # We need to be careful: escape &, <, > that aren't part of our tags
    text = _escape_outside_code(text)

    # Code blocks with language: ```python ... ```
    text = re.sub(
        r"```(\w+)?\n(.*?)```",
        lambda m: f'<pre><code class="language-{m.group(1) or ""}">{m.group(2)}</code></pre>',
        text,
        flags=re.DOTALL,
    )

    # Code blocks without language: ``` ... ```
    text = re.sub(
        r"```(.*?)```",
        lambda m: f"<pre>{m.group(1)}</pre>",
        text,
        flags=re.DOTALL,
    )

    # Inline code: `code`
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)

    # Bold: **text** or __text__
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"__(.+?)__", r"<b>\1</b>", text)

    # Italic: *text* or _text_ (but not inside words with underscores)
    text = re.sub(r"(?<!\w)\*([^*]+?)\*(?!\w)", r"<i>\1</i>", text)
    text = re.sub(r"(?<!\w)_([^_]+?)_(?!\w)", r"<i>\1</i>", text)

    # Strikethrough: ~~text~~
    text = re.sub(r"~~(.+?)~~", r"<s>\1</s>", text)

    # Links: [text](url)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)

    # Headers: # Header → bold text
    text = re.sub(r"^#{1,6}\s+(.+)$", r"<b>\1</b>", text, flags=re.MULTILINE)

    # Blockquotes: > text
    text = re.sub(
        r"^>\s?(.+)$",
        r"<blockquote>\1</blockquote>",
        text,
        flags=re.MULTILINE,
    )
    # Merge consecutive blockquotes
    text = re.sub(r"</blockquote>\n<blockquote>", "\n", text)

    return text.strip()


def _escape_outside_code(text: str) -> str:
    """Escape HTML entities in text, but leave code blocks alone."""
    parts = re.split(r"(```.*?```|`[^`]+`)", text, flags=re.DOTALL)
    result = []
    for i, part in enumerate(parts):
        if i % 2 == 0:
            # Outside code — escape
            part = part.replace("&", "&amp;")
            part = part.replace("<", "&lt;")
            part = part.replace(">", "&gt;")
        result.append(part)
    return "".join(result)


def smart_split(text: str, max_len: int = 4096) -> list[str]:
    """Split text at natural boundaries (paragraphs, lines, words)."""
    if len(text) <= max_len:
        return [text]

    chunks = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break

        # Try splitting at double newline (paragraph)
        split_at = text.rfind("\n\n", 0, max_len)
        if split_at == -1:
            # Try single newline
            split_at = text.rfind("\n", 0, max_len)
        if split_at == -1:
            # Try space
            split_at = text.rfind(" ", 0, max_len)
        if split_at == -1:
            # Hard split as last resort
            split_at = max_len

        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")

    return chunks
