import sqlite3
import os
import json
import logging
from datetime import datetime, timezone

from config import DB_PATH

logger = logging.getLogger(__name__)

_conn: sqlite3.Connection | None = None


def get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _init_schema(_conn)
    return _conn


def _init_schema(conn: sqlite3.Connection):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_messages_chat ON messages(chat_id, created_at);

        CREATE TABLE IF NOT EXISTS facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            category TEXT NOT NULL,
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(chat_id, category, key)
        );
        CREATE INDEX IF NOT EXISTS idx_facts_chat ON facts(chat_id);

        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            description TEXT NOT NULL,
            fire_at TEXT NOT NULL,
            recurrence TEXT,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_reminders_active ON reminders(active, fire_at);

        CREATE TABLE IF NOT EXISTS tool_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            tool_name TEXT NOT NULL,
            arguments TEXT,
            result TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS conversation_summaries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL UNIQUE,
            summary TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS file_uploads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            filename TEXT NOT NULL,
            path TEXT NOT NULL,
            mime_type TEXT,
            source TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_file_uploads_chat ON file_uploads(chat_id);

        CREATE TABLE IF NOT EXISTS tool_overrides (
            tool_name TEXT PRIMARY KEY,
            enabled INTEGER NOT NULL DEFAULT 1,
            description_override TEXT,
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS custom_commands (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            description TEXT NOT NULL DEFAULT '',
            prompt_template TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """)


# --- Message helpers ---

def save_message(chat_id: int, role: str, content: str):
    conn = get_conn()
    conn.execute(
        "INSERT INTO messages (chat_id, role, content) VALUES (?, ?, ?)",
        (chat_id, role, content),
    )
    conn.commit()


def get_history(chat_id: int, limit: int = 30) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT role, content FROM messages WHERE chat_id = ? ORDER BY created_at DESC LIMIT ?",
        (chat_id, limit),
    ).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


def clear_history(chat_id: int):
    conn = get_conn()
    conn.execute("DELETE FROM messages WHERE chat_id = ?", (chat_id,))
    conn.execute("DELETE FROM conversation_summaries WHERE chat_id = ?", (chat_id,))
    conn.commit()


# --- Fact helpers ---

def upsert_fact(chat_id: int, category: str, key: str, value: str):
    conn = get_conn()
    conn.execute(
        """INSERT INTO facts (chat_id, category, key, value, updated_at)
           VALUES (?, ?, ?, ?, datetime('now'))
           ON CONFLICT(chat_id, category, key)
           DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at""",
        (chat_id, category, key, value),
    )
    conn.commit()


def get_facts(chat_id: int, category: str | None = None) -> list[dict]:
    conn = get_conn()
    if category:
        rows = conn.execute(
            "SELECT category, key, value FROM facts WHERE chat_id = ? AND category = ?",
            (chat_id, category),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT category, key, value FROM facts WHERE chat_id = ?",
            (chat_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def delete_facts(chat_id: int):
    conn = get_conn()
    conn.execute("DELETE FROM facts WHERE chat_id = ?", (chat_id,))
    conn.commit()


# --- Reminder helpers ---

def create_reminder(chat_id: int, description: str, fire_at: str, recurrence: str | None = None) -> int:
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO reminders (chat_id, description, fire_at, recurrence) VALUES (?, ?, ?, ?)",
        (chat_id, description, fire_at, recurrence),
    )
    conn.commit()
    return cur.lastrowid


def get_due_reminders() -> list[dict]:
    conn = get_conn()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    rows = conn.execute(
        "SELECT id, chat_id, description, fire_at, recurrence FROM reminders WHERE active = 1 AND fire_at <= ?",
        (now,),
    ).fetchall()
    return [dict(r) for r in rows]


def deactivate_reminder(reminder_id: int):
    conn = get_conn()
    conn.execute("UPDATE reminders SET active = 0 WHERE id = ?", (reminder_id,))
    conn.commit()


def update_reminder_fire_at(reminder_id: int, new_fire_at: str):
    conn = get_conn()
    conn.execute("UPDATE reminders SET fire_at = ? WHERE id = ?", (new_fire_at, reminder_id))
    conn.commit()


def get_active_reminders(chat_id: int) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, description, fire_at, recurrence FROM reminders WHERE chat_id = ? AND active = 1 ORDER BY fire_at",
        (chat_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def cancel_reminder_by_id(chat_id: int, reminder_id: int) -> bool:
    conn = get_conn()
    cur = conn.execute(
        "UPDATE reminders SET active = 0 WHERE id = ? AND chat_id = ? AND active = 1",
        (reminder_id, chat_id),
    )
    conn.commit()
    return cur.rowcount > 0


# --- Tool log helpers ---

def log_tool_call(chat_id: int, tool_name: str, arguments: str, result: str):
    conn = get_conn()
    conn.execute(
        "INSERT INTO tool_logs (chat_id, tool_name, arguments, result) VALUES (?, ?, ?, ?)",
        (chat_id, tool_name, arguments, result),
    )
    conn.commit()


# --- Conversation summary helpers ---

def get_conversation_summary(chat_id: int) -> str | None:
    conn = get_conn()
    row = conn.execute(
        "SELECT summary FROM conversation_summaries WHERE chat_id = ?",
        (chat_id,),
    ).fetchone()
    return row["summary"] if row else None


def save_conversation_summary(chat_id: int, summary: str):
    conn = get_conn()
    conn.execute(
        """INSERT INTO conversation_summaries (chat_id, summary, updated_at)
           VALUES (?, ?, datetime('now'))
           ON CONFLICT(chat_id)
           DO UPDATE SET summary = excluded.summary, updated_at = excluded.updated_at""",
        (chat_id, summary),
    )
    conn.commit()


def get_message_count(chat_id: int) -> int:
    conn = get_conn()
    row = conn.execute(
        "SELECT COUNT(*) as cnt FROM messages WHERE chat_id = ?",
        (chat_id,),
    ).fetchone()
    return row["cnt"]


def trim_old_messages(chat_id: int, keep_recent: int = 30):
    conn = get_conn()
    conn.execute(
        """DELETE FROM messages WHERE chat_id = ? AND id NOT IN (
            SELECT id FROM messages WHERE chat_id = ? ORDER BY created_at DESC LIMIT ?
        )""",
        (chat_id, chat_id, keep_recent),
    )
    conn.commit()


def get_history_page(chat_id: int, limit: int = 10, offset: int = 0) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT role, content, created_at FROM messages WHERE chat_id = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
        (chat_id, limit, offset),
    ).fetchall()
    return [dict(r) for r in rows]


def get_stats(chat_id: int) -> dict:
    conn = get_conn()
    user_msgs = conn.execute(
        "SELECT COUNT(*) as cnt FROM messages WHERE chat_id = ? AND role = 'user'",
        (chat_id,),
    ).fetchone()["cnt"]
    assistant_msgs = conn.execute(
        "SELECT COUNT(*) as cnt FROM messages WHERE chat_id = ? AND role = 'assistant'",
        (chat_id,),
    ).fetchone()["cnt"]
    tool_calls = conn.execute(
        "SELECT tool_name, COUNT(*) as cnt FROM tool_logs WHERE chat_id = ? GROUP BY tool_name",
        (chat_id,),
    ).fetchall()
    facts_count = conn.execute(
        "SELECT COUNT(*) as cnt FROM facts WHERE chat_id = ?",
        (chat_id,),
    ).fetchone()["cnt"]
    reminders_count = conn.execute(
        "SELECT COUNT(*) as cnt FROM reminders WHERE chat_id = ? AND active = 1",
        (chat_id,),
    ).fetchone()["cnt"]

    return {
        "user_messages": user_msgs,
        "assistant_messages": assistant_msgs,
        "tool_calls": [dict(r) for r in tool_calls],
        "facts_stored": facts_count,
        "active_reminders": reminders_count,
    }


def save_file_upload(chat_id: int, filename: str, path: str, mime_type: str | None, source: str) -> int:
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO file_uploads (chat_id, filename, path, mime_type, source) VALUES (?, ?, ?, ?, ?)",
        (chat_id, filename, path, mime_type, source),
    )
    conn.commit()
    return cur.lastrowid


def get_file_upload(file_id: int) -> dict | None:
    conn = get_conn()
    row = conn.execute(
        "SELECT id, chat_id, filename, path, mime_type, source, created_at FROM file_uploads WHERE id = ?",
        (file_id,),
    ).fetchone()
    return dict(row) if row else None


def get_file_uploads(chat_id: int, limit: int = 50) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, filename, mime_type, source, created_at FROM file_uploads WHERE chat_id = ? ORDER BY created_at DESC LIMIT ?",
        (chat_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def get_history_with_offset(chat_id: int, limit: int = 30, offset: int = 0) -> list[dict]:
    """Get history skipping the most recent `offset` messages."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT role, content FROM messages WHERE chat_id = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
        (chat_id, limit, offset),
    ).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


# --- Tool override helpers ---

def get_tool_overrides() -> dict[str, dict]:
    conn = get_conn()
    rows = conn.execute("SELECT tool_name, enabled, description_override FROM tool_overrides").fetchall()
    return {r["tool_name"]: {"enabled": bool(r["enabled"]), "description_override": r["description_override"]} for r in rows}


def get_tool_override(tool_name: str) -> dict | None:
    conn = get_conn()
    row = conn.execute("SELECT tool_name, enabled, description_override FROM tool_overrides WHERE tool_name = ?", (tool_name,)).fetchone()
    return dict(row) if row else None


def upsert_tool_override(tool_name: str, enabled: bool | None = None, description_override: str | None = None):
    conn = get_conn()
    existing = get_tool_override(tool_name)
    if existing:
        if enabled is not None:
            conn.execute("UPDATE tool_overrides SET enabled = ?, updated_at = datetime('now') WHERE tool_name = ?", (int(enabled), tool_name))
        if description_override is not None:
            conn.execute("UPDATE tool_overrides SET description_override = ?, updated_at = datetime('now') WHERE tool_name = ?", (description_override or None, tool_name))
    else:
        conn.execute(
            "INSERT INTO tool_overrides (tool_name, enabled, description_override) VALUES (?, ?, ?)",
            (tool_name, int(enabled) if enabled is not None else 1, description_override),
        )
    conn.commit()


def delete_tool_override(tool_name: str):
    conn = get_conn()
    conn.execute("DELETE FROM tool_overrides WHERE tool_name = ?", (tool_name,))
    conn.commit()


# --- Custom command helpers ---

RESERVED_COMMANDS = {"start", "help", "reset", "memory", "clearmemory", "reminders", "history", "stats"}


def get_custom_commands() -> list[dict]:
    conn = get_conn()
    rows = conn.execute("SELECT id, name, description, prompt_template, created_at, updated_at FROM custom_commands ORDER BY name").fetchall()
    return [dict(r) for r in rows]


def get_custom_command(command_id: int) -> dict | None:
    conn = get_conn()
    row = conn.execute("SELECT id, name, description, prompt_template FROM custom_commands WHERE id = ?", (command_id,)).fetchone()
    return dict(row) if row else None


def get_custom_command_by_name(name: str) -> dict | None:
    conn = get_conn()
    row = conn.execute("SELECT id, name, description, prompt_template FROM custom_commands WHERE name = ?", (name.lower(),)).fetchone()
    return dict(row) if row else None


def create_custom_command(name: str, description: str, prompt_template: str) -> int:
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO custom_commands (name, description, prompt_template) VALUES (?, ?, ?)",
        (name.lower(), description, prompt_template),
    )
    conn.commit()
    return cur.lastrowid


def update_custom_command(command_id: int, name: str | None = None, description: str | None = None, prompt_template: str | None = None):
    conn = get_conn()
    if name is not None:
        conn.execute("UPDATE custom_commands SET name = ?, updated_at = datetime('now') WHERE id = ?", (name.lower(), command_id))
    if description is not None:
        conn.execute("UPDATE custom_commands SET description = ?, updated_at = datetime('now') WHERE id = ?", (description, command_id))
    if prompt_template is not None:
        conn.execute("UPDATE custom_commands SET prompt_template = ?, updated_at = datetime('now') WHERE id = ?", (prompt_template, command_id))
    conn.commit()


def delete_custom_command(command_id: int) -> bool:
    conn = get_conn()
    cur = conn.execute("DELETE FROM custom_commands WHERE id = ?", (command_id,))
    conn.commit()
    return cur.rowcount > 0
