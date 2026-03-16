import hashlib
import hmac
import json
import logging

import db

logger = logging.getLogger(__name__)

# Channel registry: name -> handler function
_CHANNEL_HANDLERS: dict[str, callable] = {}


def register_channel(name: str):
    """Decorator to register a webhook channel handler."""
    def decorator(func):
        _CHANNEL_HANDLERS[name] = func
        return func
    return decorator


def get_channel_handler(name: str):
    return _CHANNEL_HANDLERS.get(name)


def get_registered_channels() -> list[str]:
    return list(_CHANNEL_HANDLERS.keys())


def verify_signature(payload: bytes, signature: str, secret: str) -> bool:
    """Verify HMAC-SHA256 signature."""
    if not secret:
        return True  # No secret configured = skip verification
    expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(f"sha256={expected}", signature)


@register_channel("generic")
async def handle_generic_webhook(chat_id: int, payload: dict) -> str:
    """Generic fallback webhook handler."""
    event_type = payload.get("event", "unknown")
    summary = json.dumps(payload, indent=2)[:500]
    return f"Webhook received — event: {event_type}\n```\n{summary}\n```"


@register_channel("twilio")
async def handle_twilio_sms(chat_id: int, payload: dict) -> str:
    """Handle incoming SMS from Twilio."""
    from_number = payload.get("From", "unknown")
    body = payload.get("Body", "")
    return f"SMS from {from_number}: {body}"
