import logging

import db

logger = logging.getLogger(__name__)


async def request_confirmation(action: str, details: str, chat_id: int = 0) -> str:
    """Request user confirmation before performing a high-impact action."""
    try:
        conf_id = db.create_confirmation(chat_id, action, details)
        return f"CONFIRMATION_REQUIRED:{conf_id}:{action}"
    except Exception as e:
        logger.error(f"request_confirmation error: {e}")
        return f"Error requesting confirmation: {e}"


async def check_confirmation(confirmation_id: int, chat_id: int = 0) -> str:
    """Check the status of a pending confirmation."""
    try:
        conf = db.get_confirmation(confirmation_id)
        if not conf:
            return f"Confirmation #{confirmation_id} not found."

        status = conf["status"]
        if status == "approved":
            return f"Confirmation #{confirmation_id} was APPROVED. Proceed with: {conf['action']}"
        elif status == "denied":
            return f"Confirmation #{confirmation_id} was DENIED. Do not proceed with: {conf['action']}"
        else:
            return f"Confirmation #{confirmation_id} is still PENDING. Action: {conf['action']} — {conf['details']}"
    except Exception as e:
        logger.error(f"check_confirmation error: {e}")
        return f"Error checking confirmation: {e}"
