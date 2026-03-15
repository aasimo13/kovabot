import json
import logging
from datetime import datetime, timezone

from anthropic import AsyncAnthropic

import db
from config import ANTHROPIC_API_KEY, CLAUDE_MODEL, USER_TIMEZONE, BRIEFING_ENABLED, BRIEFING_TIME

logger = logging.getLogger(__name__)


async def generate_morning_briefing(context):
    """Generate and send a morning briefing to Telegram. Called by job queue."""
    if not BRIEFING_ENABLED:
        return

    try:
        # Check if it's briefing time
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo(USER_TIMEZONE))
        target_hour, target_minute = map(int, BRIEFING_TIME.split(":"))

        if now.hour != target_hour or now.minute > target_minute + 1:
            return

        # Only send once per day — check if already sent today
        today_str = now.strftime("%Y-%m-%d")
        recent = db.get_recent_notifications(chat_id=0, limit=5)
        for n in recent:
            if n["type"] == "briefing" and today_str in n.get("created_at", ""):
                return

        # Gather briefing data
        from config import WEB_CHAT_ID
        chat_id = WEB_CHAT_ID
        if not chat_id:
            return

        sections = []

        # Reminders due today
        reminders = db.get_active_reminders(chat_id)
        if reminders:
            today_reminders = [r for r in reminders if today_str in r["fire_at"]]
            if today_reminders:
                r_lines = "\n".join(f"- {r['description']} at {r['fire_at'][11:16]}" for r in today_reminders)
                sections.append(f"**Reminders today:**\n{r_lines}")

        # Google Calendar events (if connected)
        try:
            from tools.google_calendar import gcal_list_events
            events = await gcal_list_events(days=1, chat_id=chat_id)
            if events and "not connected" not in events.lower() and "no events" not in events.lower():
                sections.append(f"**Calendar today:**\n{events}")
        except Exception:
            pass

        # GitHub notifications (if connected)
        try:
            from config import GITHUB_TOKEN
            if GITHUB_TOKEN:
                from tools.github_tools import github_list_notifications
                notifs = await github_list_notifications(chat_id=chat_id)
                if notifs and "no unread" not in notifs.lower():
                    sections.append(f"**GitHub notifications:**\n{notifs}")
        except Exception:
            pass

        if not sections:
            sections.append("No events, reminders, or notifications for today.")

        # Compose briefing via LLM
        client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
        raw_data = "\n\n".join(sections)

        response = await client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=500,
            system=[{"type": "text", "text": "You are Kova. Compose a concise, friendly morning briefing from the data below. Use markdown. Be brief."}],
            messages=[
                {"role": "user", "content": f"Today is {now.strftime('%A, %B %d, %Y')}.\n\n{raw_data}"},
            ],
        )
        text_blocks = [b.text for b in response.content if b.type == "text"]
        briefing_text = "\n".join(text_blocks) if text_blocks else "Good morning!"

        # Send to Telegram
        try:
            await context.bot.send_message(chat_id=chat_id, text=briefing_text)
        except Exception as e:
            logger.error(f"Error sending briefing to Telegram: {e}")

        # Save as notification
        db.save_notification(chat_id, "briefing", f"Morning Briefing — {today_str}", briefing_text)

    except Exception as e:
        logger.error(f"Briefing error: {e}")


async def check_follow_ups(context):
    """Check for due follow-ups and send them. Called by job queue."""
    from config import FOLLOW_UP_ENABLED
    if not FOLLOW_UP_ENABLED:
        return

    try:
        due = db.get_due_follow_ups()
        for fu in due:
            chat_id = fu["chat_id"]
            message = fu["message"]

            try:
                await context.bot.send_message(chat_id=chat_id, text=f"Follow-up: {message}")
            except Exception as e:
                logger.error(f"Error sending follow-up: {e}")
                continue

            db.mark_follow_up_done(fu["id"])
            db.save_notification(chat_id, "follow_up", "Follow-up", message)
    except Exception as e:
        logger.error(f"Follow-up check error: {e}")
