import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

import db
from config import is_allowed

logger = logging.getLogger(__name__)

MESSAGES_PER_PAGE = 10


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        await update.message.reply_text("Unauthorized.")
        return
    await update.message.reply_text("Kova online. What do you need?")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        await update.message.reply_text("Unauthorized.")
        return

    keyboard = [
        [
            InlineKeyboardButton("Tools", callback_data="help_tools"),
            InlineKeyboardButton("Memory", callback_data="help_memory"),
            InlineKeyboardButton("Commands", callback_data="help_commands"),
        ]
    ]

    await update.message.reply_text(
        "<b>Kova</b> — Personal AI Agent\n\n"
        "Send me a message, photo, voice note, or file.\n"
        "I can search the web, run code, set reminders, "
        "read URLs, and remember things about you.\n\n"
        "Tap a category below for details:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML,
    )


async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        await update.message.reply_text("Unauthorized.")
        return

    keyboard = [
        [
            InlineKeyboardButton("Yes, clear history", callback_data="confirm_reset"),
            InlineKeyboardButton("Cancel", callback_data="cancel_action"),
        ]
    ]
    await update.message.reply_text(
        "Clear conversation history? Long-term memory will be preserved.",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


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
        lines.append(f"<b>[{f['category']}]</b> {f['key']}: {f['value']}")

    keyboard = [[InlineKeyboardButton("Clear All Memory", callback_data="confirm_clearmemory")]]
    await update.message.reply_text(
        "<b>Stored Facts</b>\n\n" + "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML,
    )


async def clear_memory_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        await update.message.reply_text("Unauthorized.")
        return

    keyboard = [
        [
            InlineKeyboardButton("Yes, clear memory", callback_data="confirm_clearmemory"),
            InlineKeyboardButton("Cancel", callback_data="cancel_action"),
        ]
    ]
    await update.message.reply_text(
        "Clear all long-term memory?",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


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
    buttons = []
    for r in reminders:
        line = f"<b>#{r['id']}</b> — {r['description']}\n    <i>{r['fire_at']}</i>"
        if r["recurrence"]:
            line += f" [recurs: {r['recurrence']}]"
        lines.append(line)
        buttons.append([InlineKeyboardButton(f"Cancel #{r['id']}", callback_data=f"cancel_reminder_{r['id']}")])

    await update.message.reply_text(
        "<b>Active Reminders</b>\n\n" + "\n\n".join(lines),
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode=ParseMode.HTML,
    )


async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        await update.message.reply_text("Unauthorized.")
        return
    await _send_history_page(update.effective_chat.id, 0, update=update)


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        await update.message.reply_text("Unauthorized.")
        return

    chat_id = update.effective_chat.id
    stats = db.get_stats(chat_id)

    lines = [
        "<b>Kova Stats</b>\n",
        f"Messages sent: <b>{stats['user_messages']}</b>",
        f"Responses: <b>{stats['assistant_messages']}</b>",
        f"Facts stored: <b>{stats['facts_stored']}</b>",
        f"Active reminders: <b>{stats['active_reminders']}</b>",
    ]

    if stats["tool_calls"]:
        lines.append("\n<b>Tool Usage</b>")
        for tc in stats["tool_calls"]:
            lines.append(f"  {tc['tool_name']}: {tc['cnt']}")

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def _send_history_page(chat_id: int, page: int, update: Update = None, query=None):
    """Send a page of conversation history."""
    offset = page * MESSAGES_PER_PAGE
    messages = db.get_history_page(chat_id, limit=MESSAGES_PER_PAGE, offset=offset)
    total = db.get_message_count(chat_id)
    total_pages = max(1, (total + MESSAGES_PER_PAGE - 1) // MESSAGES_PER_PAGE)

    if not messages:
        text = "No messages yet."
    else:
        lines = []
        for m in messages:
            role = "You" if m["role"] == "user" else "Kova"
            time_str = m["created_at"][11:16] if m["created_at"] else ""
            content = m["content"][:200]
            if len(m["content"]) > 200:
                content += "..."
            lines.append(f"<b>[{role}]</b> <i>{time_str}</i>\n{content}")
        text = f"<b>History</b> (page {page + 1}/{total_pages})\n\n" + "\n\n".join(lines)

    # Pagination buttons
    buttons = []
    if page > 0:
        buttons.append(InlineKeyboardButton("< Newer", callback_data=f"history_page_{page - 1}"))
    if (page + 1) < total_pages:
        buttons.append(InlineKeyboardButton("Older >", callback_data=f"history_page_{page + 1}"))

    keyboard = [buttons] if buttons else []

    if query:
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None,
            parse_mode=ParseMode.HTML,
        )
    elif update:
        await update.message.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None,
            parse_mode=ParseMode.HTML,
        )


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline keyboard button presses."""
    query = update.callback_query
    await query.answer()

    if not is_allowed(update.effective_user.id):
        return

    data = query.data
    chat_id = update.effective_chat.id

    if data == "confirm_reset":
        db.clear_history(chat_id)
        await query.edit_message_text("Conversation history cleared. Long-term memory preserved.")

    elif data == "confirm_clearmemory":
        db.delete_facts(chat_id)
        await query.edit_message_text("Long-term memory cleared.")

    elif data == "cancel_action":
        await query.edit_message_text("Cancelled.")

    elif data.startswith("cancel_reminder_"):
        rid = int(data.split("_")[-1])
        success = db.cancel_reminder_by_id(chat_id, rid)
        if success:
            await query.edit_message_text(f"Reminder #{rid} cancelled.")
        else:
            await query.edit_message_text(f"Reminder #{rid} not found or already cancelled.")

    elif data.startswith("history_page_"):
        page = int(data.split("_")[-1])
        await _send_history_page(chat_id, page, query=query)

    elif data == "help_tools":
        await query.edit_message_text(
            "<b>Tools</b>\n\n"
            "<b>Web Search</b> — Ask about news, facts, anything current\n"
            "<b>Code Execution</b> — \"Calculate...\", \"Write a script...\"\n"
            "<b>URL Reader</b> — Send a URL and I'll summarize it\n"
            "<b>Date/Time</b> — Ask what time it is anywhere\n",
            parse_mode=ParseMode.HTML,
        )

    elif data == "help_memory":
        await query.edit_message_text(
            "<b>Memory</b>\n\n"
            "I automatically remember facts about you (name, preferences, etc.)\n\n"
            "/memory — View stored facts\n"
            "/clearmemory — Erase all facts\n\n"
            "Memory persists across conversations. /reset only clears chat history.",
            parse_mode=ParseMode.HTML,
        )

    elif data == "help_commands":
        await query.edit_message_text(
            "<b>Commands</b>\n\n"
            "/help — This help menu\n"
            "/reset — Clear conversation history\n"
            "/memory — View stored facts\n"
            "/clearmemory — Clear long-term memory\n"
            "/reminders — View active reminders\n"
            "/history — Browse past messages\n"
            "/stats — Usage statistics\n",
            parse_mode=ParseMode.HTML,
        )
