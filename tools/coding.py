"""Coding agent tools — file CRUD + code execution in a per-chat workspace."""

import asyncio
import logging
import os
import pathlib

logger = logging.getLogger(__name__)

MAX_READ_CHARS = 15_000
MAX_WRITE_BYTES = 100_000  # 100 KB
MAX_DIR_ENTRIES = 200
EXEC_TIMEOUT = 30

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _workspace_path(chat_id: int) -> pathlib.Path:
    from config import WORKSPACE_DIR
    return pathlib.Path(WORKSPACE_DIR) / str(chat_id)


def _resolve_and_validate(chat_id: int, path: str) -> pathlib.Path:
    """Resolve *path* inside the chat workspace and verify it stays there."""
    ws = _workspace_path(chat_id)
    ws.mkdir(parents=True, exist_ok=True)

    target = (ws / path).resolve()
    ws_resolved = ws.resolve()

    if not str(target).startswith(str(ws_resolved) + os.sep) and target != ws_resolved:
        raise PermissionError(f"Path escapes workspace: {path}")

    return target


def _safe_env() -> dict[str, str]:
    """Minimal env for subprocess — strips API keys, keeps basics."""
    keep = {"PATH", "HOME", "USER", "LANG", "LC_ALL", "TERM", "SHELL", "TMPDIR"}
    return {k: v for k, v in os.environ.items() if k in keep}


def _human_size(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f} {unit}" if unit != "B" else f"{size} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

def read_file(path: str, chat_id: int) -> str:
    """Read a file from the workspace with line numbers."""
    try:
        target = _resolve_and_validate(chat_id, path)
    except PermissionError as e:
        return f"Refused: {e}"

    if not target.is_file():
        return f"File not found: {path}"

    try:
        content = target.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return f"Error reading file: {e}"

    if len(content) > MAX_READ_CHARS:
        content = content[:MAX_READ_CHARS]
        truncated = True
    else:
        truncated = False

    lines = content.splitlines()
    width = len(str(len(lines)))
    numbered = "\n".join(f"{i+1:>{width}} | {line}" for i, line in enumerate(lines))

    result = f"**{path}** ({_human_size(target.stat().st_size)})\n```\n{numbered}\n```"
    if truncated:
        result += f"\n⚠️ Truncated at {MAX_READ_CHARS} characters"
    return result


def write_file(path: str, content: str, chat_id: int) -> str:
    """Create or overwrite a file in the workspace."""
    try:
        target = _resolve_and_validate(chat_id, path)
    except PermissionError as e:
        return f"Refused: {e}"

    size = len(content.encode("utf-8"))
    if size > MAX_WRITE_BYTES:
        return f"Refused: content is {_human_size(size)}, limit is {_human_size(MAX_WRITE_BYTES)}"

    target.parent.mkdir(parents=True, exist_ok=True)
    existed = target.exists()

    try:
        target.write_text(content, encoding="utf-8")
    except Exception as e:
        return f"Error writing file: {e}"

    action = "Updated" if existed else "Created"
    line_count = content.count("\n") + (1 if content and not content.endswith("\n") else 0)
    return f"{action} **{path}** ({line_count} lines, {_human_size(size)})"


def edit_file(path: str, old_text: str, new_text: str, chat_id: int) -> str:
    """Find-and-replace in a workspace file. old_text must match exactly once."""
    try:
        target = _resolve_and_validate(chat_id, path)
    except PermissionError as e:
        return f"Refused: {e}"

    if not target.is_file():
        return f"File not found: {path}"

    try:
        content = target.read_text(encoding="utf-8")
    except Exception as e:
        return f"Error reading file: {e}"

    count = content.count(old_text)
    if count == 0:
        return f"old_text not found in {path}. Make sure it matches the file content exactly (including whitespace)."
    if count > 1:
        return f"old_text matches {count} locations in {path}. Provide a more specific snippet so it matches exactly once."

    new_content = content.replace(old_text, new_text, 1)

    try:
        target.write_text(new_content, encoding="utf-8")
    except Exception as e:
        return f"Error writing file: {e}"

    # Show context around the edit
    new_lines = new_content.splitlines()
    # Find where the edit landed
    edit_start = content.index(old_text)
    start_line = content[:edit_start].count("\n")
    new_text_lines = new_text.count("\n") + 1
    ctx_start = max(0, start_line - 2)
    ctx_end = min(len(new_lines), start_line + new_text_lines + 2)
    width = len(str(ctx_end))
    context = "\n".join(f"{i+1:>{width}} | {new_lines[i]}" for i in range(ctx_start, ctx_end))

    return f"Edited **{path}** (replaced {len(old_text)} chars → {len(new_text)} chars)\n```\n{context}\n```"


def list_directory(path: str = ".", recursive: bool = False, chat_id: int = 0) -> str:
    """List files and directories in the workspace."""
    try:
        target = _resolve_and_validate(chat_id, path)
    except PermissionError as e:
        return f"Refused: {e}"

    if not target.is_dir():
        return f"Not a directory: {path}"

    ws = _workspace_path(chat_id).resolve()
    entries = []
    try:
        if recursive:
            for item in sorted(target.rglob("*")):
                if len(entries) >= MAX_DIR_ENTRIES:
                    entries.append(f"... truncated at {MAX_DIR_ENTRIES} entries")
                    break
                rel = item.relative_to(ws)
                suffix = "/" if item.is_dir() else f"  ({_human_size(item.stat().st_size)})"
                entries.append(f"  {rel}{suffix}")
        else:
            for item in sorted(target.iterdir()):
                if len(entries) >= MAX_DIR_ENTRIES:
                    entries.append(f"... truncated at {MAX_DIR_ENTRIES} entries")
                    break
                rel = item.relative_to(ws)
                suffix = "/" if item.is_dir() else f"  ({_human_size(item.stat().st_size)})"
                entries.append(f"  {rel}{suffix}")
    except Exception as e:
        return f"Error listing directory: {e}"

    if not entries:
        return f"Directory **{path}** is empty."

    display_path = str(pathlib.Path(path)) if path != "." else "(workspace root)"
    return f"**{display_path}** — {len(entries)} entries\n" + "\n".join(entries)


async def execute_code(language: str, code: str, filename: str = "", chat_id: int = 0) -> str:
    """Write code to the workspace and execute it."""
    language = language.lower().strip()
    lang_config = {
        "python": {"ext": ".py", "cmd": "python3"},
        "node": {"ext": ".js", "cmd": "node"},
        "javascript": {"ext": ".js", "cmd": "node"},
        "bash": {"ext": ".sh", "cmd": "bash"},
        "sh": {"ext": ".sh", "cmd": "bash"},
    }

    if language not in lang_config:
        return f"Unsupported language: {language}. Supported: python, node/javascript, bash"

    cfg = lang_config[language]
    if not filename:
        filename = f"main{cfg['ext']}"

    try:
        target = _resolve_and_validate(chat_id, filename)
    except PermissionError as e:
        return f"Refused: {e}"

    ws = _workspace_path(chat_id).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(code, encoding="utf-8")

    try:
        process = await asyncio.create_subprocess_exec(
            cfg["cmd"], str(target),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(ws),
            env=_safe_env(),
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=EXEC_TIMEOUT
            )
        except asyncio.TimeoutError:
            process.kill()
            return f"Saved **{filename}** but execution timed out after {EXEC_TIMEOUT}s"

        parts = []
        if stdout:
            out = stdout.decode("utf-8", errors="replace")
            if len(out) > 8000:
                out = out[:8000] + "\n...(truncated)"
            parts.append(out)
        if stderr:
            err = stderr.decode("utf-8", errors="replace")
            if len(err) > 4000:
                err = err[:4000] + "\n...(truncated)"
            parts.append(f"STDERR:\n{err}")

        output = "\n".join(parts).strip() or "(no output)"
        exit_code = process.returncode

        header = f"Saved & ran **{filename}**"
        if exit_code != 0:
            header += f" — exit code {exit_code}"
        return f"{header}\n```\n{output}\n```"

    except FileNotFoundError:
        return f"Runtime not found: {cfg['cmd']}. Is {language} installed?"
    except Exception as e:
        logger.error(f"execute_code error: {e}")
        return f"Saved **{filename}** but execution failed: {e}"
