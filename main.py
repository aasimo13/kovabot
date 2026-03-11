import logging

from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
)

import db
from config import TELEGRAM_TOKEN
from handlers.commands import (
    start_command,
    reset_command,
    memory_command,
    clear_memory_command,
    reminders_command,
)
from handlers.messages import handle_text, handle_photo, handle_document
from scheduler import check_reminders

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def main():
    # Initialize database
    db.get_conn()
    logger.info("Database initialized.")

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("reset", reset_command))
    app.add_handler(CommandHandler("memory", memory_command))
    app.add_handler(CommandHandler("clearmemory", clear_memory_command))
    app.add_handler(CommandHandler("reminders", reminders_command))

    # Messages
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))

    # Scheduled tasks — check reminders every 30 seconds
    app.job_queue.run_repeating(check_reminders, interval=30, first=5)
    logger.info("Reminder scheduler started.")

    logger.info("Kova bot starting...")
    app.run_polling()


if __name__ == "__main__":
    main()
