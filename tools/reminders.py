import logging
from datetime import datetime, timezone, timedelta

import db
from config import FOLLOW_UP_ENABLED

logger = logging.getLogger(__name__)


def create_reminder(description: str, fire_at: str, recurrence: str | None = None, chat_id: int = 0) -> str:
    reminder_id = db.create_reminder(chat_id, description, fire_at, recurrence)
    msg = f"Reminder #{reminder_id} set for {fire_at}: {description}"
    if recurrence:
        msg += f" (recurs: {recurrence})"

    # Create a follow-up 24h after fire_at (Phase 4)
    if FOLLOW_UP_ENABLED and not recurrence:
        try:
            fire_dt = datetime.strptime(fire_at, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            follow_up_at = (fire_dt + timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
            db.create_follow_up(
                chat_id,
                f"Did you handle this? Reminder was: {description}",
                follow_up_at,
                source_tool="create_reminder",
                source_args=str(reminder_id),
            )
        except Exception as e:
            logger.debug(f"Follow-up creation skipped: {e}")

    return msg


def list_reminders(chat_id: int = 0) -> str:
    reminders = db.get_active_reminders(chat_id)
    if not reminders:
        return "No active reminders."

    lines = []
    for r in reminders:
        line = f"#{r['id']} — {r['description']} (at {r['fire_at']})"
        if r["recurrence"]:
            line += f" [recurs: {r['recurrence']}]"
        lines.append(line)
    return "\n".join(lines)


def cancel_reminder(reminder_id: int, chat_id: int = 0) -> str:
    success = db.cancel_reminder_by_id(chat_id, int(reminder_id))
    if success:
        return f"Reminder #{reminder_id} cancelled."
    return f"Reminder #{reminder_id} not found or already cancelled."
