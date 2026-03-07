import logging
import os
import requests
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# Config from environment variables
TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
OPENWEBUI_URL = os.environ["OPENWEBUI_URL"]  # e.g. https://open-webui-main-wsy8.onrender.com
OPENWEBUI_API_KEY = os.environ["OPENWEBUI_API_KEY"]
MODEL_ID = os.environ.get("MODEL_ID", "")  # optional, leave blank to use default
ALLOWED_USER_ID = os.environ.get("ALLOWED_USER_ID", "")  # optional, your Telegram user ID for security

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Store conversation history per chat
conversation_history = {}

def get_model():
    """Fetch available models and return the first one if MODEL_ID not set."""
    if MODEL_ID:
        return MODEL_ID
    try:
        response = requests.get(
            f"{OPENWEBUI_URL}/api/models",
            headers={"Authorization": f"Bearer {OPENWEBUI_API_KEY}"},
            timeout=10
        )
        models = response.json().get("data", [])
        if models:
            return models[0]["id"]
    except Exception as e:
        logger.error(f"Error fetching models: {e}")
    return None

def chat_with_kova(chat_id: int, user_message: str) -> str:
    """Send message to Open Web UI and return response."""
    if chat_id not in conversation_history:
        conversation_history[chat_id] = []

    conversation_history[chat_id].append({
        "role": "user",
        "content": user_message
    })

    model = get_model()
    if not model:
        return "Error: Could not find a model to use. Check your Open Web UI setup."

    payload = {
        "model": model,
        "messages": conversation_history[chat_id],
        "stream": False
    }

    try:
        response = requests.post(
            f"{OPENWEBUI_URL}/api/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENWEBUI_API_KEY}",
                "Content-Type": "application/json"
            },
            json=payload,
            timeout=60
        )
        response.raise_for_status()
        reply = response.json()["choices"][0]["message"]["content"]
        
        conversation_history[chat_id].append({
            "role": "assistant",
            "content": reply
        })
        
        return reply

    except requests.exceptions.Timeout:
        return "Request timed out. Try again."
    except Exception as e:
        logger.error(f"Error calling Open Web UI: {e}")
        return f"Something went wrong: {str(e)}"

def is_allowed(user_id: int) -> bool:
    """Check if user is allowed to use the bot."""
    if not ALLOWED_USER_ID:
        return True  # No restriction set
    return str(user_id) == ALLOWED_USER_ID

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        await update.message.reply_text("Unauthorized.")
        return
    await update.message.reply_text("Kova online. What do you need?")

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        await update.message.reply_text("Unauthorized.")
        return
    chat_id = update.effective_chat.id
    conversation_history[chat_id] = []
    await update.message.reply_text("Conversation cleared.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        await update.message.reply_text("Unauthorized.")
        return

    chat_id = update.effective_chat.id
    user_message = update.message.text

    # Show typing indicator
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")

    reply = chat_with_kova(chat_id, user_message)
    await update.message.reply_text(reply)

def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    logger.info("Kova bot starting...")
    app.run_polling()

if __name__ == "__main__":
    main()

