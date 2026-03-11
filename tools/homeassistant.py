import json
import logging

import aiohttp

from config import HA_URL, HA_TOKEN

logger = logging.getLogger(__name__)


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {HA_TOKEN}",
        "Content-Type": "application/json",
    }


async def ha_list_entities(domain: str = "", chat_id: int = 0) -> str:
    """List Home Assistant entities, optionally filtered by domain (e.g. 'light', 'switch')."""
    try:
        async with aiohttp.ClientSession() as session:
            url = f"{HA_URL}/api/states"
            async with session.get(url, headers=_headers(), timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    return f"Home Assistant API error: {resp.status}"
                states = await resp.json()

        if domain:
            states = [s for s in states if s["entity_id"].startswith(f"{domain}.")]

        if not states:
            return f"No entities found{' for domain ' + domain if domain else ''}."

        lines = []
        for s in states[:30]:
            name = s.get("attributes", {}).get("friendly_name", s["entity_id"])
            state = s["state"]
            lines.append(f"- {name} (`{s['entity_id']}`): {state}")
        if len(states) > 30:
            lines.append(f"... and {len(states) - 30} more")
        return "\n".join(lines)
    except Exception as e:
        logger.error(f"ha_list_entities error: {e}")
        return f"Error listing entities: {e}"


async def ha_get_state(entity_id: str, chat_id: int = 0) -> str:
    """Get the current state and attributes of a Home Assistant entity."""
    try:
        async with aiohttp.ClientSession() as session:
            url = f"{HA_URL}/api/states/{entity_id}"
            async with session.get(url, headers=_headers(), timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 404:
                    return f"Entity '{entity_id}' not found."
                if resp.status != 200:
                    return f"Home Assistant API error: {resp.status}"
                state = await resp.json()

        attrs = state.get("attributes", {})
        name = attrs.get("friendly_name", entity_id)
        lines = [
            f"**{name}** (`{entity_id}`)",
            f"State: {state['state']}",
            f"Last changed: {state.get('last_changed', 'unknown')}",
        ]
        # Include key attributes
        for key in ["brightness", "color_temp", "temperature", "current_temperature",
                     "hvac_action", "unit_of_measurement", "battery_level"]:
            if key in attrs:
                lines.append(f"{key}: {attrs[key]}")
        return "\n".join(lines)
    except Exception as e:
        logger.error(f"ha_get_state error: {e}")
        return f"Error getting state: {e}"


async def ha_call_service(domain: str, service: str, entity_id: str, data: str = "{}", chat_id: int = 0) -> str:
    """Call a Home Assistant service (e.g. domain='light', service='turn_on', entity_id='light.living_room')."""
    try:
        service_data = json.loads(data) if data else {}
        service_data["entity_id"] = entity_id

        async with aiohttp.ClientSession() as session:
            url = f"{HA_URL}/api/services/{domain}/{service}"
            async with session.post(url, headers=_headers(), json=service_data, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status not in (200, 201):
                    err = await resp.text()
                    return f"Home Assistant API error: {resp.status} — {err[:200]}"

        return f"Service {domain}.{service} called on {entity_id}."
    except json.JSONDecodeError:
        return "Error: 'data' parameter must be valid JSON."
    except Exception as e:
        logger.error(f"ha_call_service error: {e}")
        return f"Error calling service: {e}"


async def ha_get_history(entity_id: str, hours: int = 24, chat_id: int = 0) -> str:
    """Get state history for a Home Assistant entity over the last N hours."""
    try:
        from datetime import datetime, timezone, timedelta
        start = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()

        async with aiohttp.ClientSession() as session:
            url = f"{HA_URL}/api/history/period/{start}?filter_entity_id={entity_id}&minimal_response"
            async with session.get(url, headers=_headers(), timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    return f"Home Assistant API error: {resp.status}"
                history = await resp.json()

        if not history or not history[0]:
            return f"No history found for {entity_id} in the last {hours} hours."

        entries = history[0]
        lines = [f"History for `{entity_id}` (last {hours}h):"]
        for entry in entries[-20:]:  # Last 20 entries
            state = entry["state"]
            changed = entry.get("last_changed", "")[:19]
            lines.append(f"- {changed}: {state}")
        if len(entries) > 20:
            lines.append(f"... showing last 20 of {len(entries)} entries")
        return "\n".join(lines)
    except Exception as e:
        logger.error(f"ha_get_history error: {e}")
        return f"Error getting history: {e}"
