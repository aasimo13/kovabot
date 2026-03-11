import asyncio
import logging
import os

import uvicorn
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

import db
from config import TELEGRAM_TOKEN
from handlers.commands import (
    start_command,
    help_command,
    reset_command,
    memory_command,
    clear_memory_command,
    reminders_command,
    history_command,
    stats_command,
    handle_callback,
)
from handlers.messages import handle_text, handle_photo, handle_document, handle_voice, handle_custom_command
from scheduler import check_reminders
from proactive import generate_morning_briefing, check_follow_ups
from web import create_web_app

# Import webhook channel modules so their decorators register
import webhooks  # noqa: F401
import webhooks_github  # noqa: F401
import webhooks_homeassistant  # noqa: F401

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def error_handler(update, context):
    """Global error handler — log and notify user."""
    logger.error(f"Unhandled exception: {context.error}", exc_info=context.error)
    if update and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "Something went wrong on my end. Try again in a moment."
            )
        except Exception:
            pass


def build_telegram_app():
    """Build and configure the Telegram application (without starting it)."""
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("reset", reset_command))
    app.add_handler(CommandHandler("memory", memory_command))
    app.add_handler(CommandHandler("clearmemory", clear_memory_command))
    app.add_handler(CommandHandler("reminders", reminders_command))
    app.add_handler(CommandHandler("history", history_command))
    app.add_handler(CommandHandler("stats", stats_command))

    # Catch-all for custom commands (after all built-in CommandHandlers)
    app.add_handler(MessageHandler(filters.COMMAND, handle_custom_command))

    # Inline keyboard callbacks
    app.add_handler(CallbackQueryHandler(handle_callback))

    # Messages
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_voice))

    # Global error handler
    app.add_error_handler(error_handler)

    # Scheduled tasks
    app.job_queue.run_repeating(check_reminders, interval=30, first=5)
    app.job_queue.run_repeating(generate_morning_briefing, interval=60, first=30)
    app.job_queue.run_repeating(check_follow_ups, interval=300, first=60)

    return app


async def main():
    # Initialize database
    db.get_conn()
    logger.info("Database initialized.")

    # Build and start Telegram bot (manual lifecycle)
    tg_app = build_telegram_app()
    await tg_app.initialize()
    await tg_app.start()
    await tg_app.updater.start_polling()
    logger.info("Telegram bot polling started.")

    # Start FastAPI web dashboard alongside
    port = int(os.environ.get("PORT", "8080"))
    fastapi_app = create_web_app()
    config = uvicorn.Config(fastapi_app, host="0.0.0.0", port=port, log_level="info")
    server = uvicorn.Server(config)

    logger.info(f"Web dashboard starting on port {port}...")

    try:
        await server.serve()
    finally:
        logger.info("Shutting down...")
        await tg_app.updater.stop()
        await tg_app.stop()
        await tg_app.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
