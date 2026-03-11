import base64
import logging
from email.mime.text import MIMEText

import aiohttp

from google_auth import get_valid_token

logger = logging.getLogger(__name__)

GMAIL_API = "https://gmail.googleapis.com/gmail/v1/users/me"


async def _get_headers(chat_id: int) -> dict | None:
    token = await get_valid_token(chat_id)
    if not token:
        return None
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


async def gmail_search(query: str, max_results: int = 5, chat_id: int = 0) -> str:
    """Search emails by query (same syntax as Gmail search bar)."""
    headers = await _get_headers(chat_id)
    if not headers:
        return "Gmail not connected. Connect via the dashboard Integrations tab."

    try:
        async with aiohttp.ClientSession() as session:
            url = f"{GMAIL_API}/messages?q={query}&maxResults={max_results}"
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    return f"Gmail API error: {resp.status}"
                data = await resp.json()

            messages = data.get("messages", [])
            if not messages:
                return f"No emails found matching '{query}'."

            lines = []
            for msg_ref in messages:
                msg_url = f"{GMAIL_API}/messages/{msg_ref['id']}?format=metadata&metadataHeaders=Subject&metadataHeaders=From&metadataHeaders=Date"
                async with session.get(msg_url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp2:
                    if resp2.status != 200:
                        continue
                    msg = await resp2.json()

                msg_headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
                subject = msg_headers.get("Subject", "(No subject)")
                sender = msg_headers.get("From", "unknown")
                date = msg_headers.get("Date", "")[:25]
                snippet = msg.get("snippet", "")[:100]
                lines.append(f"- **{subject}** from {sender} ({date})\n  ID: `{msg_ref['id']}` — {snippet}")

        return "\n".join(lines) if lines else "No readable emails found."
    except Exception as e:
        logger.error(f"gmail_search error: {e}")
        return f"Error searching email: {e}"


async def gmail_read(message_id: str, chat_id: int = 0) -> str:
    """Read the full content of an email by message ID."""
    headers = await _get_headers(chat_id)
    if not headers:
        return "Gmail not connected. Connect via the dashboard Integrations tab."

    try:
        async with aiohttp.ClientSession() as session:
            url = f"{GMAIL_API}/messages/{message_id}?format=full"
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    return f"Gmail API error: {resp.status}"
                msg = await resp.json()

        msg_headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
        subject = msg_headers.get("Subject", "(No subject)")
        sender = msg_headers.get("From", "unknown")
        date = msg_headers.get("Date", "")
        to = msg_headers.get("To", "")

        # Extract body
        body = _extract_body(msg.get("payload", {}))

        lines = [
            f"**{subject}**",
            f"From: {sender}",
            f"To: {to}",
            f"Date: {date}",
            f"\n{body[:3000]}",
        ]
        return "\n".join(lines)
    except Exception as e:
        logger.error(f"gmail_read error: {e}")
        return f"Error reading email: {e}"


def _extract_body(payload: dict) -> str:
    """Extract plain text body from Gmail message payload."""
    if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")

    for part in payload.get("parts", []):
        result = _extract_body(part)
        if result:
            return result

    # Fallback to body data if present
    if payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")

    return "(No readable text content)"


async def gmail_send(to: str, subject: str, body: str, chat_id: int = 0) -> str:
    """Send an email."""
    headers = await _get_headers(chat_id)
    if not headers:
        return "Gmail not connected. Connect via the dashboard Integrations tab."

    try:
        message = MIMEText(body)
        message["to"] = to
        message["subject"] = subject
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")

        async with aiohttp.ClientSession() as session:
            url = f"{GMAIL_API}/messages/send"
            async with session.post(url, headers=headers, json={"raw": raw}, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status not in (200, 201):
                    err = await resp.text()
                    return f"Gmail API error: {resp.status} — {err[:200]}"
                result = await resp.json()

        return f"Email sent to {to} (ID: {result.get('id', 'unknown')})"
    except Exception as e:
        logger.error(f"gmail_send error: {e}")
        return f"Error sending email: {e}"


async def gmail_create_draft(to: str, subject: str, body: str, chat_id: int = 0) -> str:
    """Create an email draft."""
    headers = await _get_headers(chat_id)
    if not headers:
        return "Gmail not connected. Connect via the dashboard Integrations tab."

    try:
        message = MIMEText(body)
        message["to"] = to
        message["subject"] = subject
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")

        async with aiohttp.ClientSession() as session:
            url = f"{GMAIL_API}/drafts"
            payload = {"message": {"raw": raw}}
            async with session.post(url, headers=headers, json=payload, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status not in (200, 201):
                    err = await resp.text()
                    return f"Gmail API error: {resp.status} — {err[:200]}"
                result = await resp.json()

        return f"Draft created (ID: {result.get('id', 'unknown')})"
    except Exception as e:
        logger.error(f"gmail_create_draft error: {e}")
        return f"Error creating draft: {e}"
