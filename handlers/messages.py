import asyncio
import base64
import logging

from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from config import is_allowed
from agent import run_agent
from formatting import markdown_to_telegram_html, smart_split

logger = logging.getLogger(__name__)


async def _keep_typing(bot, chat_id: int):
    """Send typing indicator every 4 seconds until cancelled."""
    try:
        while True:
            await bot.send_chat_action(chat_id=chat_id, action="typing")
            await asyncio.sleep(4)
    except asyncio.CancelledError:
        pass


async def _send_reply(update: Update, text: str, status_message=None):
    """Send formatted reply, falling back to plain text if HTML fails."""
    if not text:
        text = "(empty response)"

    # Delete status message if it exists
    if status_message:
        try:
            await status_message.delete()
        except Exception:
            pass

    html_text = markdown_to_telegram_html(text)
    chunks = smart_split(html_text)

    for chunk in chunks:
        try:
            await update.message.reply_text(
                chunk,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        except Exception:
            # Fallback to plain text if HTML parsing fails
            plain_chunks = smart_split(text)
            for plain_chunk in plain_chunks:
                await update.message.reply_text(plain_chunk)
            break


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        await update.message.reply_text("Unauthorized.")
        return

    chat_id = update.effective_chat.id
    user_message = update.message.text

    typing_task = asyncio.create_task(_keep_typing(context.bot, chat_id))
    status_message = None

    async def status_callback(status_text: str):
        nonlocal status_message
        try:
            if status_message:
                await status_message.edit_text(f"_{status_text}_", parse_mode=ParseMode.MARKDOWN_V2)
            else:
                status_message = await update.message.reply_text(
                    f"_{status_text}_", parse_mode=ParseMode.MARKDOWN_V2
                )
        except Exception:
            pass

    try:
        reply = await run_agent(chat_id, user_message, status_callback=status_callback)
        await _send_reply(update, reply, status_message)
    except Exception as e:
        logger.error(f"Error in handle_text: {e}", exc_info=True)
        await update.message.reply_text("Something went wrong. Try again.")
    finally:
        typing_task.cancel()


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        await update.message.reply_text("Unauthorized.")
        return

    chat_id = update.effective_chat.id
    typing_task = asyncio.create_task(_keep_typing(context.bot, chat_id))

    try:
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        photo_bytes = await file.download_as_bytearray()
        b64 = base64.b64encode(photo_bytes).decode("utf-8")

        caption = update.message.caption or "What's in this image?"

        content = [
            {"type": "text", "text": caption},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
        ]

        reply = await run_agent(chat_id, content)
        await _send_reply(update, reply)
    except Exception as e:
        logger.error(f"Error in handle_photo: {e}", exc_info=True)
        await update.message.reply_text("Something went wrong processing that image.")
    finally:
        typing_task.cancel()


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        await update.message.reply_text("Unauthorized.")
        return

    chat_id = update.effective_chat.id
    typing_task = asyncio.create_task(_keep_typing(context.bot, chat_id))

    try:
        doc = update.message.document
        mime = doc.mime_type or ""

        file = await context.bot.get_file(doc.file_id)
        file_bytes = await file.download_as_bytearray()
        caption = update.message.caption or ""

        if mime.startswith("image/"):
            b64 = base64.b64encode(file_bytes).decode("utf-8")
            content = [
                {"type": "text", "text": caption or "What's in this image?"},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
            ]
            reply = await run_agent(chat_id, content)
        else:
            try:
                text = file_bytes.decode("utf-8")
            except UnicodeDecodeError:
                await update.message.reply_text("I can only process text files and images.")
                return

            if len(text) > 10000:
                text = text[:10000] + "\n...(truncated)"

            user_message = f"[File: {doc.file_name}]\n{text}"
            if caption:
                user_message = f"{caption}\n\n{user_message}"

            reply = await run_agent(chat_id, user_message)

        await _send_reply(update, reply)
    except Exception as e:
        logger.error(f"Error in handle_document: {e}", exc_info=True)
        await update.message.reply_text("Something went wrong processing that file.")
    finally:
        typing_task.cancel()


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        await update.message.reply_text("Unauthorized.")
        return

    chat_id = update.effective_chat.id
    typing_task = asyncio.create_task(_keep_typing(context.bot, chat_id))

    try:
        voice = update.message.voice or update.message.audio
        file = await context.bot.get_file(voice.file_id)
        file_bytes = await file.download_as_bytearray()

        # Write to temp file for Whisper API
        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name

        try:
            from openai import AsyncOpenAI
            from config import OPENAI_API_KEY
            client = AsyncOpenAI(api_key=OPENAI_API_KEY)

            with open(tmp_path, "rb") as audio_file:
                transcription = await client.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio_file,
                )
            transcript = transcription.text
        finally:
            os.unlink(tmp_path)

        if not transcript:
            await update.message.reply_text("Couldn't transcribe that audio.")
            return

        status_message = None

        async def status_callback(status_text: str):
            nonlocal status_message
            try:
                if status_message:
                    await status_message.edit_text(f"_{status_text}_", parse_mode=ParseMode.MARKDOWN_V2)
                else:
                    status_message = await update.message.reply_text(
                        f"_{status_text}_", parse_mode=ParseMode.MARKDOWN_V2
                    )
            except Exception:
                pass

        reply = await run_agent(chat_id, transcript, status_callback=status_callback)
        await _send_reply(update, reply, status_message)
    except Exception as e:
        logger.error(f"Error in handle_voice: {e}", exc_info=True)
        await update.message.reply_text("Something went wrong processing that voice message.")
    finally:
        typing_task.cancel()
