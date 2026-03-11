import logging
from webhooks import register_channel

logger = logging.getLogger(__name__)


@register_channel("homeassistant")
async def handle_homeassistant_webhook(chat_id: int, payload: dict) -> str:
    """Parse Home Assistant webhook events (state changes)."""
    event_type = payload.get("event_type", payload.get("type", "unknown"))
    entity_id = payload.get("entity_id", "")
    new_state = payload.get("new_state", payload.get("state", ""))
    old_state = payload.get("old_state", "")

    if entity_id:
        parts = [f"HA state change: `{entity_id}`"]
        if old_state:
            parts.append(f"  {old_state} -> {new_state}")
        else:
            parts.append(f"  State: {new_state}")
        return "\n".join(parts)

    return f"Home Assistant event: {event_type}"
