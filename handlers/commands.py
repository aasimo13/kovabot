import json
import logging

from anthropic import AsyncAnthropic
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

import db
from config import is_allowed, ANTHROPIC_API_KEY, CLAUDE_MODEL, MODEL_ID

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
            "/stats — Usage statistics\n"
            "/diagnostics — Check tool calling health\n",
            parse_mode=ParseMode.HTML,
        )


async def diagnostics_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Live diagnostics: test LLM backends, tool calling, and show config."""
    if not is_allowed(update.effective_user.id):
        await update.message.reply_text("Unauthorized.")
        return

    await update.message.reply_text("Running diagnostics (this takes a few seconds)...")

    from tools import TOOL_REGISTRY, TOOL_SCHEMAS
    from agent import _get_effective_tool_schemas, _build_system_prompt, _recent_llm_calls, _openai_to_anthropic_tools

    model = MODEL_ID or CLAUDE_MODEL
    lines = ["<b>Kova Diagnostics</b>\n"]

    # 1. Config check
    lines.append("<b>Config</b>")
    lines.append(f"  ANTHROPIC_API_KEY: {'set' if ANTHROPIC_API_KEY else 'NOT SET'}")
    lines.append(f"  Model: {model}")
    lines.append(f"  Registered tools: {len(TOOL_REGISTRY)}")

    effective = _get_effective_tool_schemas()
    lines.append(f"  Effective tool schemas: {len(effective)}")
    tool_names = [s["function"]["name"] for s in effective]
    lines.append(f"  Tools: {', '.join(tool_names[:10])}")
    if len(tool_names) > 10:
        lines.append(f"    ...and {len(tool_names) - 10} more")

    # 2. Simple tool test (1 tool, 1 message)
    lines.append("\n<b>Simple Tool Test (1 tool)</b>")
    if ANTHROPIC_API_KEY:
        try:
            test_client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
            test_tools = [{
                "name": "test_tool",
                "description": "Test tool",
                "input_schema": {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]},
            }]
            response = await test_client.messages.create(
                model=model,
                max_tokens=100,
                messages=[{"role": "user", "content": "Call the test_tool with x='hello'"}],
                tools=test_tools,
                tool_choice={"type": "auto"},
            )
            if response and response.content:
                has_tc = any(b.type == "tool_use" for b in response.content)
                lines.append(f"  Status: OK (tool_calls={has_tc})")
            else:
                lines.append("  Status: FAIL — empty response")
        except Exception as e:
            lines.append(f"  Status: FAIL — {e}")
    else:
        lines.append("  Status: SKIPPED — no API key")

    # 3. FULL agent-style test (all tools, real system prompt)
    lines.append("\n<b>Full Agent Test (all {0} tools)</b>".format(len(effective)))
    if ANTHROPIC_API_KEY:
        try:
            chat_id = update.effective_chat.id
            system_prompt = _build_system_prompt(chat_id)
            anthropic_tools = _openai_to_anthropic_tools(effective)

            lines.append(f"  System prompt: {len(system_prompt)} chars")
            lines.append(f"  Tool schemas: {len(effective)}")

            full_client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
            response = await full_client.messages.create(
                model=model,
                max_tokens=200,
                system=[{"type": "text", "text": system_prompt}],
                messages=[{"role": "user", "content": "What are the top news headlines today?"}],
                tools=anthropic_tools,
                tool_choice={"type": "auto"},
            )
            if response and response.content:
                tool_blocks = [b for b in response.content if b.type == "tool_use"]
                text_blocks = [b for b in response.content if b.type == "text"]
                has_tc = bool(tool_blocks)
                lines.append(f"  Status: OK")
                lines.append(f"  Tool calls: {has_tc}")
                if has_tc:
                    for b in tool_blocks:
                        lines.append(f"    → {b.name}({json.dumps(b.input)[:80]})")
                if text_blocks:
                    lines.append(f"  Content: {text_blocks[0].text[:100]}")
            else:
                lines.append("  Status: FAIL — empty response")
        except Exception as e:
            err_str = str(e)
            lines.append(f"  Status: FAIL")
            lines.append(f"  Error: {err_str[:300]}")
    else:
        lines.append("  Status: SKIPPED — no API key")

    # 4. Recent LLM calls
    lines.append(f"\n<b>Recent LLM Calls ({len(_recent_llm_calls)})</b>")
    if _recent_llm_calls:
        for call in list(_recent_llm_calls)[-5:]:
            status = call.get("status", "?")
            t = call.get("time", "?")
            if status == "ok":
                tools_used = call.get("tool_calls", [])
                lines.append(f"  [{t}] OK via {call.get('backend')} → {', '.join(tools_used) if tools_used else 'no tools used'}")
            elif status == "FAILED":
                lines.append(f"  [{t}] FAILED via {call.get('backend')}: {call.get('error', '?')[:100]}")
            elif status == "fallback":
                lines.append(f"  [{t}] FALLBACK via {call.get('backend')} ({call.get('reason', '?')})")
    else:
        lines.append("  No calls recorded yet (send a message first)")

    # 5. Developer mode
    dev_mode = db.get_setting("developer_mode", "false")
    lines.append(f"\n<b>Developer mode:</b> {dev_mode}")

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)
