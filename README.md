# Kova

An autonomous Telegram AI agent built on Anthropic Claude. Kova chats over Telegram, remembers what you tell it, picks the right tools for a task, and runs multi-step work on its own — with a FastAPI web dashboard riding alongside the bot.

> Personal project, working and actively developed. It runs on a single Python process and is designed to deploy to [Railway](https://railway.app).

## What it does

- **Telegram-native agent** — talk to it like any chat. It handles text, photos (vision), documents, and voice notes.
- **Persistent memory** — facts and conversation context are stored in SQLite. Older conversations are summarized automatically, and an OpenAI-embedding vector store powers semantic recall so it can find relevant past context.
- **Tool use** — Claude drives an agent loop that calls tools, chains their results, runs them in parallel, and retries on failure (see the tool kit below).
- **Web dashboard** — a FastAPI app runs in the same process, exposing a chat UI plus endpoints to browse history, memory, files, plans, tools, diagnostics, and settings.
- **Proactive behavior** — optional morning briefings and follow-up checks via scheduled jobs.
- **Webhooks** — inbound channels for GitHub and Home Assistant events.

## Tool kit

Kova ships with around two dozen built-in tools that are always available, plus optional integrations that register themselves only when you provide their credentials.

**Always available**
- Web: `brave_search`, `fetch_url`, `deep_research`
- Reasoning & planning: `think`, `create_plan`, `update_plan_step`, `get_plan`
- Memory: `store_fact`, `recall_facts`, `semantic_recall`
- Time & reminders: `get_current_datetime`, `create_reminder`, `list_reminders`, `cancel_reminder`
- Code & files: `execute_python`, `execute_code`, `read_file`, `write_file`, `edit_file`, `list_directory`, `run_command`, `generate_file` (the file/shell tools require developer mode)
- Agent control: `spawn_agent` (parallel sub-agents), `request_confirmation`, `check_confirmation`, `get_agent_context`
- Voice: `text_to_speech`

**Optional integrations** (activate when their env vars are set)
- **GitHub** (`GITHUB_TOKEN`) — list repos, search/create issues, read PRs, browse repo trees and file contents
- **Home Assistant** (`HA_URL` + `HA_TOKEN`) — list entities, read state, call services, get history
- **Twilio SMS** (`TWILIO_*`) — send SMS and read history
- **Google** (`GOOGLE_CLIENT_ID` etc.) — Gmail search/read/send/draft and Google Calendar list/create/search/free-busy

You can also enable/disable tools and define custom tools at runtime from the dashboard.

## Architecture

- `main.py` — boots the Telegram bot (long-polling) and the FastAPI dashboard together in one async process.
- `agent.py` — the Claude agent loop: builds the system prompt, calls the Anthropic Messages API with prompt caching, executes tool calls (in parallel, with retries), and summarizes long conversations.
- `tools/` — one module per tool; tools are auto-registered into `TOOL_REGISTRY` / `TOOL_SCHEMAS`.
- `db.py` — SQLite layer for messages, facts, reminders, plans, files, settings, custom tools, and memory vectors.
- `web.py` — FastAPI dashboard and JSON API.
- `webhooks*.py` — inbound webhook channels (GitHub, Home Assistant).
- `handlers/` — Telegram command and message handlers.

## Telegram commands

`/start`, `/help`, `/reset`, `/memory`, `/clearmemory`, `/reminders`, `/history`, `/stats`, `/diagnostics` — plus any custom commands you define in the dashboard.

## Tech stack

Python 3.11 · [Anthropic Claude](https://www.anthropic.com) (via the `anthropic` SDK) · `python-telegram-bot` · FastAPI + Uvicorn · SQLite · OpenAI embeddings/TTS · Brave Search · Railway (Nixpacks).

## Running it

Requires Python 3.11+.

```bash
pip install -r requirements.txt
python main.py
```

`main.py` starts both the bot and the dashboard. The dashboard listens on `PORT` (default `8080`).

### Environment variables

At minimum you need `TELEGRAM_BOT_TOKEN` and `ANTHROPIC_API_KEY`. Everything else is optional and unlocks more capability.

| Variable | Required | Description |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | yes | Bot token from [@BotFather](https://t.me/BotFather) |
| `ANTHROPIC_API_KEY` | yes | Claude API key — powers the agent |
| `ALLOWED_USER_ID` | recommended | Your Telegram user ID; locks the bot to only you |
| `CLAUDE_MODEL` | no | Model id (default `claude-haiku-4-5-20251001`) |
| `OPENAI_API_KEY` | no | Used for embeddings (semantic memory), TTS, and voice transcription |
| `BRAVE_API_KEY` | no | Enables web search and deep research |
| `DB_PATH` | no | SQLite path (default `/data/kova.db`) |
| `USER_TIMEZONE` | no | IANA timezone for reminders (default `UTC`) |
| `MAX_TOOL_ROUNDS` | no | Max agent tool-loop iterations (default `15`) |
| `WEB_AUTH_TOKEN` / `WEB_CHAT_ID` | no | Auth token and chat binding for the web dashboard |
| `WEBHOOK_SECRET` | no | Shared secret for inbound webhooks |
| `GITHUB_TOKEN` | no | Enables the GitHub tools |
| `HA_URL` / `HA_TOKEN` | no | Enables the Home Assistant tools |
| `TWILIO_ACCOUNT_SID` / `TWILIO_AUTH_TOKEN` / `TWILIO_PHONE_NUMBER` | no | Enables Twilio SMS |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` / `GOOGLE_REDIRECT_URI` | no | Enables Gmail and Google Calendar (OAuth2) |
| `TTS_ENABLED` / `TTS_MODEL` / `TTS_VOICE` | no | Text-to-speech settings |
| `BRIEFING_ENABLED` / `BRIEFING_TIME` / `FOLLOW_UP_ENABLED` | no | Proactive briefing and follow-up jobs |
| `WORKSPACE_DIR` | no | Persistent coding workspace path (default `/data/workspace`) |

## Deploy on Railway

The repo includes a `Procfile` and `nixpacks.toml`, so it deploys on Railway with no extra build config:

1. Create a Railway project from this GitHub repo.
2. Add the environment variables above (set a persistent volume for `DB_PATH` / `WORKSPACE_DIR` so memory survives restarts).
3. Deploy — Railway runs `python main.py`.

## Status

Working and actively developed as a personal project. Optional integrations are gated behind their credentials, so the bot runs fine with just a Telegram token and an Anthropic key.

## License

MIT — see [LICENSE](LICENSE).
