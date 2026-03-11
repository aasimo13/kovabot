import db


def create_reminder(description: str, fire_at: str, recurrence: str | None = None, chat_id: int = 0) -> str:
    reminder_id = db.create_reminder(chat_id, description, fire_at, recurrence)
    msg = f"Reminder #{reminder_id} set for {fire_at}: {description}"
    if recurrence:
        msg += f" (recurs: {recurrence})"
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
