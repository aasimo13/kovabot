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

        CREATE TABLE IF NOT EXISTS custom_tools (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            description TEXT NOT NULL,
            parameters TEXT NOT NULL DEFAULT '[]',
            code_body TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        -- Phase 1: Webhook events
        CREATE TABLE IF NOT EXISTS webhook_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            channel TEXT NOT NULL,
            payload TEXT NOT NULL,
            processed INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_webhook_events_chat ON webhook_events(chat_id, created_at);

        -- Phase 3: OAuth tokens
        CREATE TABLE IF NOT EXISTS oauth_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            provider TEXT NOT NULL,
            access_token TEXT NOT NULL,
            refresh_token TEXT NOT NULL DEFAULT '',
            expires_at TEXT NOT NULL,
            scope TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(chat_id, provider)
        );

        -- Phase 4: Notifications
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            type TEXT NOT NULL,
            title TEXT NOT NULL,
            body TEXT NOT NULL DEFAULT '',
            read INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_notifications_chat ON notifications(chat_id, read, created_at);

        -- Phase 4: Follow-ups
        CREATE TABLE IF NOT EXISTS follow_ups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            message TEXT NOT NULL,
            fire_at TEXT NOT NULL,
            done INTEGER NOT NULL DEFAULT 0,
            source_tool TEXT NOT NULL DEFAULT '',
            source_args TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_follow_ups_due ON follow_ups(done, fire_at);

        -- Phase 5: Memory vectors
        CREATE TABLE IF NOT EXISTS memory_vectors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            source_type TEXT NOT NULL,
            source_id TEXT NOT NULL DEFAULT '',
            content TEXT NOT NULL,
            embedding TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_memory_vectors_chat ON memory_vectors(chat_id, source_type);

        -- Phase 6: Plans
        CREATE TABLE IF NOT EXISTS plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            steps TEXT NOT NULL DEFAULT '[]',
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_plans_chat ON plans(chat_id, status);

        -- Phase 6: Confirmations
        CREATE TABLE IF NOT EXISTS confirmations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            details TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_confirmations_chat ON confirmations(chat_id, status);

        -- Settings (key-value store for runtime configuration)
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
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


# --- Custom tool helpers ---

def get_custom_tools(enabled_only: bool = True) -> list[dict]:
    conn = get_conn()
    if enabled_only:
        rows = conn.execute("SELECT id, name, description, parameters, code_body, enabled FROM custom_tools WHERE enabled = 1 ORDER BY name").fetchall()
    else:
        rows = conn.execute("SELECT id, name, description, parameters, code_body, enabled, created_at, updated_at FROM custom_tools ORDER BY name").fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["parameters"] = json.loads(d["parameters"])
        result.append(d)
    return result


def get_custom_tool(tool_id: int) -> dict | None:
    conn = get_conn()
    row = conn.execute("SELECT id, name, description, parameters, code_body, enabled FROM custom_tools WHERE id = ?", (tool_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["parameters"] = json.loads(d["parameters"])
    return d


def get_custom_tool_by_name(name: str) -> dict | None:
    conn = get_conn()
    row = conn.execute("SELECT id, name, description, parameters, code_body, enabled FROM custom_tools WHERE name = ?", (name,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["parameters"] = json.loads(d["parameters"])
    return d


def create_custom_tool(name: str, description: str, parameters: list, code_body: str) -> int:
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO custom_tools (name, description, parameters, code_body) VALUES (?, ?, ?, ?)",
        (name, description, json.dumps(parameters), code_body),
    )
    conn.commit()
    return cur.lastrowid


def update_custom_tool(tool_id: int, name: str | None = None, description: str | None = None,
                       parameters: list | None = None, code_body: str | None = None, enabled: bool | None = None):
    conn = get_conn()
    if name is not None:
        conn.execute("UPDATE custom_tools SET name = ?, updated_at = datetime('now') WHERE id = ?", (name, tool_id))
    if description is not None:
        conn.execute("UPDATE custom_tools SET description = ?, updated_at = datetime('now') WHERE id = ?", (description, tool_id))
    if parameters is not None:
        conn.execute("UPDATE custom_tools SET parameters = ?, updated_at = datetime('now') WHERE id = ?", (json.dumps(parameters), tool_id))
    if code_body is not None:
        conn.execute("UPDATE custom_tools SET code_body = ?, updated_at = datetime('now') WHERE id = ?", (code_body, tool_id))
    if enabled is not None:
        conn.execute("UPDATE custom_tools SET enabled = ?, updated_at = datetime('now') WHERE id = ?", (int(enabled), tool_id))
    conn.commit()


def delete_custom_tool(tool_id: int) -> bool:
    conn = get_conn()
    cur = conn.execute("DELETE FROM custom_tools WHERE id = ?", (tool_id,))
    conn.commit()
    return cur.rowcount > 0


# --- Webhook event helpers ---

def log_webhook_event(chat_id: int, channel: str, payload: str):
    conn = get_conn()
    conn.execute(
        "INSERT INTO webhook_events (chat_id, channel, payload) VALUES (?, ?, ?)",
        (chat_id, channel, payload),
    )
    conn.commit()


def get_recent_webhook_events(chat_id: int, limit: int = 20) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, channel, payload, processed, created_at FROM webhook_events WHERE chat_id = ? ORDER BY created_at DESC LIMIT ?",
        (chat_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


# --- OAuth token helpers ---

def save_oauth_token(chat_id: int, provider: str, access_token: str, refresh_token: str,
                     expires_at: str, scope: str = ""):
    conn = get_conn()
    conn.execute(
        """INSERT INTO oauth_tokens (chat_id, provider, access_token, refresh_token, expires_at, scope, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
           ON CONFLICT(chat_id, provider)
           DO UPDATE SET access_token = excluded.access_token,
                         refresh_token = CASE WHEN excluded.refresh_token = '' THEN oauth_tokens.refresh_token ELSE excluded.refresh_token END,
                         expires_at = excluded.expires_at,
                         scope = excluded.scope,
                         updated_at = excluded.updated_at""",
        (chat_id, provider, access_token, refresh_token, expires_at, scope),
    )
    conn.commit()


def get_oauth_token(chat_id: int, provider: str) -> dict | None:
    conn = get_conn()
    row = conn.execute(
        "SELECT chat_id, provider, access_token, refresh_token, expires_at, scope FROM oauth_tokens WHERE chat_id = ? AND provider = ?",
        (chat_id, provider),
    ).fetchone()
    return dict(row) if row else None


def delete_oauth_token(chat_id: int, provider: str):
    conn = get_conn()
    conn.execute("DELETE FROM oauth_tokens WHERE chat_id = ? AND provider = ?", (chat_id, provider))
    conn.commit()


# --- Notification helpers ---

def save_notification(chat_id: int, type: str, title: str, body: str = ""):
    conn = get_conn()
    conn.execute(
        "INSERT INTO notifications (chat_id, type, title, body) VALUES (?, ?, ?, ?)",
        (chat_id, type, title, body),
    )
    conn.commit()


def get_notifications(chat_id: int, limit: int = 30, unread_only: bool = False) -> list[dict]:
    conn = get_conn()
    query = "SELECT id, type, title, body, read, created_at FROM notifications WHERE chat_id = ?"
    if unread_only:
        query += " AND read = 0"
    query += " ORDER BY created_at DESC LIMIT ?"
    rows = conn.execute(query, (chat_id, limit)).fetchall()
    return [dict(r) for r in rows]


def get_recent_notifications(chat_id: int, limit: int = 5) -> list[dict]:
    return get_notifications(chat_id, limit=limit)


def get_unread_notification_count(chat_id: int) -> int:
    conn = get_conn()
    row = conn.execute(
        "SELECT COUNT(*) as cnt FROM notifications WHERE chat_id = ? AND read = 0",
        (chat_id,),
    ).fetchone()
    return row["cnt"]


def mark_notification_read(notification_id: int):
    conn = get_conn()
    conn.execute("UPDATE notifications SET read = 1 WHERE id = ?", (notification_id,))
    conn.commit()


# --- Follow-up helpers ---

def create_follow_up(chat_id: int, message: str, fire_at: str, source_tool: str = "", source_args: str = ""):
    conn = get_conn()
    conn.execute(
        "INSERT INTO follow_ups (chat_id, message, fire_at, source_tool, source_args) VALUES (?, ?, ?, ?, ?)",
        (chat_id, message, fire_at, source_tool, source_args),
    )
    conn.commit()


def get_due_follow_ups() -> list[dict]:
    conn = get_conn()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    rows = conn.execute(
        "SELECT id, chat_id, message, fire_at FROM follow_ups WHERE done = 0 AND fire_at <= ?",
        (now,),
    ).fetchall()
    return [dict(r) for r in rows]


def mark_follow_up_done(follow_up_id: int):
    conn = get_conn()
    conn.execute("UPDATE follow_ups SET done = 1 WHERE id = ?", (follow_up_id,))
    conn.commit()


# --- Memory vector helpers ---

def save_memory_vector(chat_id: int, source_type: str, source_id: str, content: str, embedding: list[float]):
    conn = get_conn()
    # Remove existing vector for same source
    conn.execute(
        "DELETE FROM memory_vectors WHERE chat_id = ? AND source_type = ? AND source_id = ?",
        (chat_id, source_type, source_id),
    )
    conn.execute(
        "INSERT INTO memory_vectors (chat_id, source_type, source_id, content, embedding) VALUES (?, ?, ?, ?, ?)",
        (chat_id, source_type, source_id, content, json.dumps(embedding)),
    )
    conn.commit()


def get_memory_vectors(chat_id: int) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT source_type, source_id, content, embedding FROM memory_vectors WHERE chat_id = ?",
        (chat_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def delete_memory_vectors_for_source(chat_id: int, source_type: str, source_id: str):
    conn = get_conn()
    conn.execute(
        "DELETE FROM memory_vectors WHERE chat_id = ? AND source_type = ? AND source_id = ?",
        (chat_id, source_type, source_id),
    )
    conn.commit()


# --- Plan helpers ---

def create_plan(chat_id: int, title: str, steps: list[dict]) -> int:
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO plans (chat_id, title, steps) VALUES (?, ?, ?)",
        (chat_id, title, json.dumps(steps)),
    )
    conn.commit()
    return cur.lastrowid


def get_plan(plan_id: int) -> dict | None:
    conn = get_conn()
    row = conn.execute(
        "SELECT id, chat_id, title, steps, status, created_at, updated_at FROM plans WHERE id = ?",
        (plan_id,),
    ).fetchone()
    if not row:
        return None
    d = dict(row)
    d["steps"] = json.loads(d["steps"])
    return d


def get_active_plans(chat_id: int) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, chat_id, title, steps, status, created_at FROM plans WHERE chat_id = ? AND status = 'active' ORDER BY created_at DESC",
        (chat_id,),
    ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["steps"] = json.loads(d["steps"])
        result.append(d)
    return result


def update_plan(plan_id: int, steps: list[dict], status: str):
    conn = get_conn()
    conn.execute(
        "UPDATE plans SET steps = ?, status = ?, updated_at = datetime('now') WHERE id = ?",
        (json.dumps(steps), status, plan_id),
    )
    conn.commit()


# --- Confirmation helpers ---

def create_confirmation(chat_id: int, action: str, details: str) -> int:
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO confirmations (chat_id, action, details) VALUES (?, ?, ?)",
        (chat_id, action, details),
    )
    conn.commit()
    return cur.lastrowid


def get_confirmation(confirmation_id: int) -> dict | None:
    conn = get_conn()
    row = conn.execute(
        "SELECT id, chat_id, action, details, status, created_at FROM confirmations WHERE id = ?",
        (confirmation_id,),
    ).fetchone()
    return dict(row) if row else None


def get_pending_confirmation(chat_id: int) -> dict | None:
    conn = get_conn()
    row = conn.execute(
        "SELECT id, chat_id, action, details, status FROM confirmations WHERE chat_id = ? AND status = 'pending' ORDER BY created_at DESC LIMIT 1",
        (chat_id,),
    ).fetchone()
    return dict(row) if row else None


def update_confirmation_status(confirmation_id: int, status: str):
    conn = get_conn()
    conn.execute(
        "UPDATE confirmations SET status = ?, updated_at = datetime('now') WHERE id = ?",
        (status, confirmation_id),
    )
    conn.commit()


# --- Settings helpers ---

def get_setting(key: str, default: str = "") -> str:
    conn = get_conn()
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(key: str, value: str):
    conn = get_conn()
    conn.execute(
        """INSERT INTO settings (key, value, updated_at) VALUES (?, ?, datetime('now'))
           ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at""",
        (key, value),
    )
    conn.commit()


def get_all_settings() -> dict:
    conn = get_conn()
    rows = conn.execute("SELECT key, value FROM settings").fetchall()
    return {r["key"]: r["value"] for r in rows}


def delete_setting(key: str):
    conn = get_conn()
    conn.execute("DELETE FROM settings WHERE key = ?", (key,))
    conn.commit()


# --- Fact deletion helper ---

def delete_fact_by_id(chat_id: int, category: str, key: str) -> bool:
    conn = get_conn()
    cur = conn.execute(
        "DELETE FROM facts WHERE chat_id = ? AND category = ? AND key = ?",
        (chat_id, category, key),
    )
    conn.commit()
    return cur.rowcount > 0
