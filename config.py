import os

# Telegram
TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
ALLOWED_USER_ID = os.environ.get("ALLOWED_USER_ID", "")

# LLM backend — point at Open Web UI or directly at OpenAI
OPENWEBUI_URL = os.environ.get("OPENWEBUI_URL", "")
OPENWEBUI_API_KEY = os.environ.get("OPENWEBUI_API_KEY", "")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
MODEL_ID = os.environ.get("MODEL_ID", "")

# Brave Search
BRAVE_API_KEY = os.environ.get("BRAVE_API_KEY", "")

# Database
DB_PATH = os.environ.get("DB_PATH", "/data/kova.db")

# Agent
MAX_TOOL_ROUNDS = int(os.environ.get("MAX_TOOL_ROUNDS", "10"))
USER_TIMEZONE = os.environ.get("USER_TIMEZONE", "UTC")

SYSTEM_PROMPT = """You are Kova, a capable personal AI assistant on Telegram.

You have tools available and should use them proactively:
- Search the web for current information when asked about news, facts, or anything you're unsure about.
- Store important facts about the user (preferences, name, etc.) to long-term memory so you remember across conversations.
- Create reminders when asked to remind the user of something.
- Run Python code for calculations, data processing, or anything computational.
- Check the current date/time when it's relevant.

Be concise and direct. Don't narrate your tool usage — just use tools and give the answer.
When you store a fact, do it silently unless the user specifically asks about memory.
"""


def is_allowed(user_id: int) -> bool:
    if not ALLOWED_USER_ID:
        return True
    return str(user_id) == ALLOWED_USER_ID
