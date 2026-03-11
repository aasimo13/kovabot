import base64
import logging

from telegram import Update
from telegram.ext import ContextTypes

from config import is_allowed
from agent import run_agent

logger = logging.getLogger(__name__)

TELEGRAM_MAX_LEN = 4096


async def _send_long_message(update: Update, text: str):
    """Send a message, chunking if it exceeds Telegram's 4096 char limit."""
    if not text:
        text = "(empty response)"
    for i in range(0, len(text), TELEGRAM_MAX_LEN):
        await update.message.reply_text(text[i : i + TELEGRAM_MAX_LEN])


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        await update.message.reply_text("Unauthorized.")
        return

    chat_id = update.effective_chat.id
    user_message = update.message.text

    await context.bot.send_chat_action(chat_id=chat_id, action="typing")

    reply = await run_agent(chat_id, user_message)
    await _send_long_message(update, reply)


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        await update.message.reply_text("Unauthorized.")
        return

    chat_id = update.effective_chat.id
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")

    # Get highest resolution photo
    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)
    photo_bytes = await file.download_as_bytearray()
    b64 = base64.b64encode(photo_bytes).decode("utf-8")

    caption = update.message.caption or "What's in this image?"

    content = [
        {"type": "text", "text": caption},
        {
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
        },
    ]

    reply = await run_agent(chat_id, content)
    await _send_long_message(update, reply)


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        await update.message.reply_text("Unauthorized.")
        return

    chat_id = update.effective_chat.id
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")

    doc = update.message.document
    mime = doc.mime_type or ""

    file = await context.bot.get_file(doc.file_id)
    file_bytes = await file.download_as_bytearray()

    caption = update.message.caption or ""

    # Image documents → vision
    if mime.startswith("image/"):
        b64 = base64.b64encode(file_bytes).decode("utf-8")
        ext = mime.split("/")[-1]
        content = [
            {"type": "text", "text": caption or "What's in this image?"},
            {
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{b64}"},
            },
        ]
        reply = await run_agent(chat_id, content)
    else:
        # Text-based documents
        try:
            text = file_bytes.decode("utf-8")
        except UnicodeDecodeError:
            await update.message.reply_text("I can only process text files and images.")
            return

        # Truncate very long files
        if len(text) > 10000:
            text = text[:10000] + "\n...(truncated)"

        user_message = f"[File: {doc.file_name}]\n{text}"
        if caption:
            user_message = f"{caption}\n\n{user_message}"

        reply = await run_agent(chat_id, user_message)

    await _send_long_message(update, reply)
