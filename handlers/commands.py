import logging

from telegram import Update
from telegram.ext import ContextTypes

import db
from config import is_allowed

logger = logging.getLogger(__name__)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        await update.message.reply_text("Unauthorized.")
        return
    await update.message.reply_text("Kova online. What do you need?")


async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        await update.message.reply_text("Unauthorized.")
        return
    chat_id = update.effective_chat.id
    db.clear_history(chat_id)
    await update.message.reply_text("Conversation history cleared. Long-term memory preserved.")


async def memory_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        await update.message.reply_text("Unauthorized.")
        return
    chat_id = update.effective_chat.id
    facts = db.get_facts(chat_id)
    if not facts:
        await update.message.reply_text("No facts stored in memory.")
        return

    lines = []
    for f in facts:
        lines.append(f"[{f['category']}] {f['key']}: {f['value']}")
    await update.message.reply_text("Stored facts:\n" + "\n".join(lines))


async def clear_memory_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        await update.message.reply_text("Unauthorized.")
        return
    chat_id = update.effective_chat.id
    db.delete_facts(chat_id)
    await update.message.reply_text("Long-term memory cleared.")


async def reminders_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        await update.message.reply_text("Unauthorized.")
        return
    chat_id = update.effective_chat.id
    reminders = db.get_active_reminders(chat_id)
    if not reminders:
        await update.message.reply_text("No active reminders.")
        return

    lines = []
    for r in reminders:
        line = f"#{r['id']} — {r['description']} (at {r['fire_at']})"
        if r["recurrence"]:
            line += f" [recurs: {r['recurrence']}]"
        lines.append(line)
    await update.message.reply_text("Active reminders:\n" + "\n".join(lines))
