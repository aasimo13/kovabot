import logging
from datetime import datetime, timezone

from croniter import croniter
from telegram.ext import ContextTypes

import db

logger = logging.getLogger(__name__)


async def check_reminders(context: ContextTypes.DEFAULT_TYPE):
    """Called every 30 seconds by JobQueue. Fires due reminders."""
    try:
        due = db.get_due_reminders()
    except Exception as e:
        logger.error(f"Error checking reminders: {e}")
        return

    for reminder in due:
        rid = reminder["id"]
        chat_id = reminder["chat_id"]
        desc = reminder["description"]
        recurrence = reminder["recurrence"]

        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"Reminder: {desc}",
            )
            logger.info(f"Fired reminder #{rid} for chat {chat_id}")
        except Exception as e:
            logger.error(f"Error sending reminder #{rid}: {e}")
            continue

        if recurrence:
            # Schedule next occurrence
            try:
                now = datetime.now(timezone.utc)
                cron = croniter(recurrence, now)
                next_fire = cron.get_next(datetime)
                db.update_reminder_fire_at(rid, next_fire.strftime("%Y-%m-%d %H:%M:%S"))
                logger.info(f"Rescheduled reminder #{rid} to {next_fire}")
            except Exception as e:
                logger.error(f"Error rescheduling reminder #{rid}: {e}")
                db.deactivate_reminder(rid)
        else:
            db.deactivate_reminder(rid)
