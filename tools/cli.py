import asyncio
import logging
import shlex

logger = logging.getLogger(__name__)

MAX_OUTPUT = 8000
TIMEOUT_SECONDS = 30

# Commands that are always blocked — destructive or dangerous
BLOCKED_COMMANDS = {
    "rm", "rmdir", "mkfs", "dd", "shutdown", "reboot", "poweroff",
    "halt", "init", "kill", "killall", "pkill", "chmod", "chown",
    "passwd", "su", "sudo", "mount", "umount", "fdisk", "fsck",
    "systemctl", "service", "iptables", "nft",
}

# Patterns blocked anywhere in the command string
BLOCKED_PATTERNS = [
    "> /dev/",
    "| rm",
    "&& rm",
    "; rm",
    ":(){ :",  # fork bomb
]


def _is_safe(command: str) -> tuple[bool, str]:
    """Check if a command is safe to execute."""
    stripped = command.strip()
    if not stripped:
        return False, "Empty command"

    # Parse first token as the base command
    try:
        tokens = shlex.split(stripped)
    except ValueError:
        tokens = stripped.split()

    base = tokens[0].split("/")[-1]  # handle /usr/bin/curl etc.

    if base in BLOCKED_COMMANDS:
        return False, f"Command '{base}' is blocked for safety"

    for pattern in BLOCKED_PATTERNS:
        if pattern in stripped:
            return False, f"Blocked pattern detected in command"

    return True, ""


async def run_command(command: str, chat_id: int = 0) -> str:
    """Execute a CLI command and return its output."""
    safe, reason = _is_safe(command)
    if not safe:
        return f"Refused: {reason}"

    try:
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            # Don't inherit env vars with secrets — build a clean env
            env=_safe_env(),
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=TIMEOUT_SECONDS
            )
        except asyncio.TimeoutError:
            process.kill()
            return f"Command timed out after {TIMEOUT_SECONDS}s"

        output_parts = []
        if stdout:
            out = stdout.decode("utf-8", errors="replace")
            if len(out) > MAX_OUTPUT:
                out = out[:MAX_OUTPUT] + "\n...(truncated)"
            output_parts.append(out)
        if stderr:
            err = stderr.decode("utf-8", errors="replace")
            if len(err) > MAX_OUTPUT:
                err = err[:MAX_OUTPUT] + "\n...(truncated)"
            output_parts.append(f"STDERR:\n{err}")

        exit_code = process.returncode
        result = "\n".join(output_parts).strip()
        if not result:
            result = "(no output)"

        if exit_code != 0:
            result = f"Exit code {exit_code}\n{result}"

        return result

    except Exception as e:
        logger.error(f"run_command error: {e}")
        return f"Error: {e}"


def _safe_env():
    """Build a minimal environment for subprocess execution.
    Strips API keys and secrets, keeps PATH and basic locale."""
    import os
    keep_keys = {"PATH", "HOME", "USER", "LANG", "LC_ALL", "TERM", "SHELL", "TMPDIR"}
    return {k: v for k, v in os.environ.items() if k in keep_keys}
