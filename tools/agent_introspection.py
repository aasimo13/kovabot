import logging

import db

logger = logging.getLogger(__name__)


async def get_agent_context(chat_id: int = 0) -> str:
    """Inspect the agent's own available tools, memory, and current state."""
    try:
        # Lazy import to avoid circular dependency (tools/__init__.py imports this module)
        from tools import TOOL_REGISTRY

        lines = []

        # Available tools
        overrides = db.get_tool_overrides()
        enabled_builtin = []
        disabled_builtin = []
        for name in TOOL_REGISTRY:
            override = overrides.get(name)
            if override and not override["enabled"]:
                disabled_builtin.append(name)
            else:
                enabled_builtin.append(name)

        lines.append(f"**Built-in tools ({len(enabled_builtin)} enabled, {len(disabled_builtin)} disabled):**")
        lines.append(f"  Enabled: {', '.join(enabled_builtin)}")
        if disabled_builtin:
            lines.append(f"  Disabled: {', '.join(disabled_builtin)}")

        # Custom tools
        custom = db.get_custom_tools(enabled_only=False)
        if custom:
            enabled_custom = [t["name"] for t in custom if t["enabled"]]
            lines.append(f"**Custom tools ({len(enabled_custom)} enabled):** {', '.join(enabled_custom)}")

        # Facts count
        facts = db.get_facts(chat_id)
        lines.append(f"**Facts stored:** {len(facts)}")

        # Active reminders
        reminders = db.get_active_reminders(chat_id)
        lines.append(f"**Active reminders:** {len(reminders)}")

        # Active plans
        plans = db.get_active_plans(chat_id)
        if plans:
            lines.append(f"**Active plans:** {len(plans)}")
            for p in plans:
                completed = sum(1 for s in p["steps"] if s["status"] == "completed")
                total = len(p["steps"])
                lines.append(f"  - {p['title']} ({completed}/{total} done)")

        # Pending confirmations
        pending = db.get_pending_confirmation(chat_id)
        if pending:
            lines.append(f"**Pending confirmation:** {pending['action']} — {pending['details']}")

        return "\n".join(lines)
    except Exception as e:
        logger.error(f"get_agent_context error: {e}")
        return f"Error getting agent context: {e}"
