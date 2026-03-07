## requirements.txt

```
python-telegram-bot==21.3
requests==2.31.0
```

---

## README.md

```markdown
# Kova Telegram Bot

Bridges Telegram with Open Web UI (Kova).

## Environment Variables

Set these in Railway (or wherever you deploy):

| Variable | Description |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Token from BotFather |
| `OPENWEBUI_URL` | Your Open Web UI URL, no trailing slash |
| `OPENWEBUI_API_KEY` | API key from Open Web UI settings |
| `MODEL_ID` | (Optional) Specific model ID to use. Leave blank to auto-select first available. |
| `ALLOWED_USER_ID` | (Optional but recommended) Your Telegram user ID. Locks the bot to only you. |

## Commands

- `/start` — Wake up Kova
- `/reset` — Clear conversation history and start fresh

## Getting your Telegram User ID

Message @userinfobot on Telegram — it will tell you your user ID.

## Deploy on Railway

1. Push this repo to GitHub
2. Go to railway.app, create new project from GitHub repo
3. Add environment variables
4. Deploy — done
```
