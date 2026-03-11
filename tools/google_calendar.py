import json
import logging
from datetime import datetime, timezone, timedelta

import aiohttp

from google_auth import get_valid_token

logger = logging.getLogger(__name__)

CALENDAR_API = "https://www.googleapis.com/calendar/v3"


async def _get_headers(chat_id: int) -> dict | None:
    token = await get_valid_token(chat_id)
    if not token:
        return None
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


async def gcal_list_events(days: int = 7, query: str = "", chat_id: int = 0) -> str:
    """List upcoming calendar events for the next N days."""
    headers = await _get_headers(chat_id)
    if not headers:
        return "Google Calendar not connected. Connect via the dashboard Integrations tab."

    try:
        now = datetime.now(timezone.utc)
        time_min = now.isoformat()
        time_max = (now + timedelta(days=days)).isoformat()

        params = f"timeMin={time_min}&timeMax={time_max}&singleEvents=true&orderBy=startTime&maxResults=20"
        if query:
            params += f"&q={query}"

        async with aiohttp.ClientSession() as session:
            url = f"{CALENDAR_API}/calendars/primary/events?{params}"
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    return f"Calendar API error: {resp.status}"
                data = await resp.json()

        events = data.get("items", [])
        if not events:
            return f"No events found in the next {days} days."

        lines = []
        for e in events:
            start = e.get("start", {})
            start_str = start.get("dateTime", start.get("date", ""))[:16]
            summary = e.get("summary", "(No title)")
            location = e.get("location", "")
            line = f"- **{summary}** — {start_str}"
            if location:
                line += f" ({location})"
            lines.append(line)
        return "\n".join(lines)
    except Exception as e:
        logger.error(f"gcal_list_events error: {e}")
        return f"Error listing events: {e}"


async def gcal_create_event(title: str, start: str, end: str, description: str = "", location: str = "", chat_id: int = 0) -> str:
    """Create a new calendar event. Start/end format: YYYY-MM-DDTHH:MM:SS or YYYY-MM-DD."""
    headers = await _get_headers(chat_id)
    if not headers:
        return "Google Calendar not connected. Connect via the dashboard Integrations tab."

    try:
        event_body = {"summary": title}

        # Handle all-day vs timed events
        if "T" in start:
            event_body["start"] = {"dateTime": start, "timeZone": "UTC"}
            event_body["end"] = {"dateTime": end, "timeZone": "UTC"}
        else:
            event_body["start"] = {"date": start}
            event_body["end"] = {"date": end}

        if description:
            event_body["description"] = description
        if location:
            event_body["location"] = location

        async with aiohttp.ClientSession() as session:
            url = f"{CALENDAR_API}/calendars/primary/events"
            async with session.post(url, headers=headers, json=event_body, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status not in (200, 201):
                    err = await resp.text()
                    return f"Calendar API error: {resp.status} — {err[:200]}"
                created = await resp.json()

        return f"Event created: **{created.get('summary')}** — {created.get('htmlLink', '')}"
    except Exception as e:
        logger.error(f"gcal_create_event error: {e}")
        return f"Error creating event: {e}"


async def gcal_free_busy(date: str, chat_id: int = 0) -> str:
    """Check free/busy status for a specific date (YYYY-MM-DD)."""
    headers = await _get_headers(chat_id)
    if not headers:
        return "Google Calendar not connected. Connect via the dashboard Integrations tab."

    try:
        time_min = f"{date}T00:00:00Z"
        time_max = f"{date}T23:59:59Z"

        body = {
            "timeMin": time_min,
            "timeMax": time_max,
            "items": [{"id": "primary"}],
        }

        async with aiohttp.ClientSession() as session:
            url = f"{CALENDAR_API}/freeBusy"
            async with session.post(url, headers=headers, json=body, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    return f"Calendar API error: {resp.status}"
                data = await resp.json()

        busy_periods = data.get("calendars", {}).get("primary", {}).get("busy", [])
        if not busy_periods:
            return f"You're free all day on {date}!"

        lines = [f"Busy periods on {date}:"]
        for period in busy_periods:
            start = period["start"][:16]
            end = period["end"][:16]
            lines.append(f"- {start} to {end}")
        return "\n".join(lines)
    except Exception as e:
        logger.error(f"gcal_free_busy error: {e}")
        return f"Error checking free/busy: {e}"


async def gcal_search_events(query: str, chat_id: int = 0) -> str:
    """Search calendar events by keyword."""
    return await gcal_list_events(days=90, query=query, chat_id=chat_id)
