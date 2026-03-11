from tools.datetime_tools import get_current_datetime
from tools.web_search import brave_search
from tools.memory import store_fact, recall_facts
from tools.reminders import create_reminder, list_reminders, cancel_reminder
from tools.code_exec import execute_python
from tools.fetch_url import fetch_url
from tools.generate_file import generate_file
from tools.tts import text_to_speech
from tools.semantic_memory import semantic_recall
from tools.planning import create_plan, update_plan_step, get_plan
from tools.confirmation import request_confirmation, check_confirmation
from tools.agent_introspection import get_agent_context
from tools.cli import run_command

# Maps function name → callable
TOOL_REGISTRY: dict[str, callable] = {
    "get_current_datetime": get_current_datetime,
    "brave_search": brave_search,
    "store_fact": store_fact,
    "recall_facts": recall_facts,
    "create_reminder": create_reminder,
    "list_reminders": list_reminders,
    "cancel_reminder": cancel_reminder,
    "execute_python": execute_python,
    "fetch_url": fetch_url,
    "generate_file": generate_file,
    "text_to_speech": text_to_speech,
    "semantic_recall": semantic_recall,
    "create_plan": create_plan,
    "update_plan_step": update_plan_step,
    "get_plan": get_plan,
    "request_confirmation": request_confirmation,
    "check_confirmation": check_confirmation,
    "get_agent_context": get_agent_context,
    "run_command": run_command,
}

# Conditionally register GitHub tools
try:
    from config import GITHUB_TOKEN
    if GITHUB_TOKEN:
        from tools.github_tools import (
            github_list_repos, github_search_issues, github_create_issue,
            github_get_pull_request, github_list_notifications,
            github_get_repo_tree, github_get_file_content,
        )
        TOOL_REGISTRY.update({
            "github_list_repos": github_list_repos,
            "github_search_issues": github_search_issues,
            "github_create_issue": github_create_issue,
            "github_get_pull_request": github_get_pull_request,
            "github_list_notifications": github_list_notifications,
            "github_get_repo_tree": github_get_repo_tree,
            "github_get_file_content": github_get_file_content,
        })
except Exception:
    pass

# Conditionally register Home Assistant tools
try:
    from config import HA_URL, HA_TOKEN
    if HA_URL and HA_TOKEN:
        from tools.homeassistant import (
            ha_list_entities, ha_get_state, ha_call_service, ha_get_history,
        )
        TOOL_REGISTRY.update({
            "ha_list_entities": ha_list_entities,
            "ha_get_state": ha_get_state,
            "ha_call_service": ha_call_service,
            "ha_get_history": ha_get_history,
        })
except Exception:
    pass

# Conditionally register Google tools
try:
    from config import GOOGLE_CLIENT_ID
    if GOOGLE_CLIENT_ID:
        from tools.google_calendar import (
            gcal_list_events, gcal_create_event, gcal_free_busy, gcal_search_events,
        )
        from tools.gmail import (
            gmail_search, gmail_read, gmail_send, gmail_create_draft,
        )
        TOOL_REGISTRY.update({
            "gcal_list_events": gcal_list_events,
            "gcal_create_event": gcal_create_event,
            "gcal_free_busy": gcal_free_busy,
            "gcal_search_events": gcal_search_events,
            "gmail_search": gmail_search,
            "gmail_read": gmail_read,
            "gmail_send": gmail_send,
            "gmail_create_draft": gmail_create_draft,
        })
except Exception:
    pass


# OpenAI-format function schemas
TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "get_current_datetime",
            "description": "Get the current date and time. Use this whenever you need to know the current time, e.g. for scheduling reminders.",
            "parameters": {
                "type": "object",
                "properties": {
                    "timezone": {
                        "type": "string",
                        "description": "IANA timezone name, e.g. 'America/New_York'. Defaults to user's configured timezone.",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "brave_search",
            "description": "Search the web using Brave Search. Use this for current events, facts, or anything you're unsure about.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query.",
                    },
                    "count": {
                        "type": "integer",
                        "description": "Number of results (1-10, default 5).",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "store_fact",
            "description": "Store a fact about the user to long-term memory. Use this proactively when the user shares personal info (name, preferences, etc.).",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "description": "Fact category, e.g. 'personal', 'preferences', 'work'.",
                    },
                    "key": {
                        "type": "string",
                        "description": "Fact key, e.g. 'name', 'favorite_color'.",
                    },
                    "value": {
                        "type": "string",
                        "description": "The fact value.",
                    },
                },
                "required": ["category", "key", "value"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recall_facts",
            "description": "Retrieve stored facts about the user from long-term memory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "description": "Optional category filter.",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_reminder",
            "description": "Create a reminder. Always call get_current_datetime first to know the current time, then set fire_at as an absolute UTC datetime.",
            "parameters": {
                "type": "object",
                "properties": {
                    "description": {
                        "type": "string",
                        "description": "What to remind the user about.",
                    },
                    "fire_at": {
                        "type": "string",
                        "description": "When to fire, in UTC as 'YYYY-MM-DD HH:MM:SS'.",
                    },
                    "recurrence": {
                        "type": "string",
                        "description": "Optional cron expression for recurring reminders, e.g. '0 9 * * *' for daily at 9am UTC.",
                    },
                },
                "required": ["description", "fire_at"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_reminders",
            "description": "List all active reminders for this chat.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cancel_reminder",
            "description": "Cancel an active reminder by its ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "reminder_id": {
                        "type": "integer",
                        "description": "The reminder ID to cancel.",
                    }
                },
                "required": ["reminder_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "execute_python",
            "description": "Execute Python code in a sandboxed environment. Available modules: math, statistics, json, re, datetime, random, itertools, collections. Use print() to produce output.",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "Python code to execute.",
                    }
                },
                "required": ["code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_url",
            "description": "Fetch and read the content of a URL/webpage. Use this when the user shares a link or asks you to read/summarize a webpage.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The URL to fetch.",
                    }
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_file",
            "description": "Create a file and send it to the user. Use this when asked to create documents, export data, write code files, generate reports, etc.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": "The filename with extension, e.g. 'report.txt', 'data.csv', 'script.py'.",
                    },
                    "content": {
                        "type": "string",
                        "description": "The text content of the file.",
                    },
                },
                "required": ["filename", "content"],
            },
        },
    },
    # Phase 1: TTS
    {
        "type": "function",
        "function": {
            "name": "text_to_speech",
            "description": "Convert text to a voice audio message. Use when the user asks you to read something aloud or sends a voice message.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "The text to convert to speech.",
                    }
                },
                "required": ["text"],
            },
        },
    },
    # Phase 5: Semantic Memory
    {
        "type": "function",
        "function": {
            "name": "semantic_recall",
            "description": "Search long-term memory by semantic similarity/meaning. Use this when keyword recall isn't enough — finds related facts by meaning.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "What to search for in memory.",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "Number of results to return (default 5).",
                    },
                },
                "required": ["query"],
            },
        },
    },
    # Phase 6: Planning
    {
        "type": "function",
        "function": {
            "name": "create_plan",
            "description": "Create a multi-step plan for complex tasks. Steps can be a JSON array or newline-separated text.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Title of the plan.",
                    },
                    "steps": {
                        "type": "string",
                        "description": "Steps as a JSON array of strings or newline-separated text.",
                    },
                },
                "required": ["title", "steps"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_plan_step",
            "description": "Update a step in an active plan with its status and result.",
            "parameters": {
                "type": "object",
                "properties": {
                    "plan_id": {
                        "type": "integer",
                        "description": "The plan ID.",
                    },
                    "step_index": {
                        "type": "integer",
                        "description": "Zero-based index of the step to update.",
                    },
                    "status": {
                        "type": "string",
                        "description": "New status: pending, in_progress, completed, or failed.",
                    },
                    "result": {
                        "type": "string",
                        "description": "Optional result or output from the step.",
                    },
                },
                "required": ["plan_id", "step_index", "status"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_plan",
            "description": "View the current status of a plan with all steps and progress.",
            "parameters": {
                "type": "object",
                "properties": {
                    "plan_id": {
                        "type": "integer",
                        "description": "The plan ID.",
                    }
                },
                "required": ["plan_id"],
            },
        },
    },
    # Phase 6: Confirmation
    {
        "type": "function",
        "function": {
            "name": "request_confirmation",
            "description": "Request user confirmation before performing a high-impact action (sending email, creating events, controlling devices).",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "Short description of the action, e.g. 'send_email', 'create_event'.",
                    },
                    "details": {
                        "type": "string",
                        "description": "Detailed description of what will happen.",
                    },
                },
                "required": ["action", "details"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_confirmation",
            "description": "Check the status of a pending confirmation (approved, denied, or still pending).",
            "parameters": {
                "type": "object",
                "properties": {
                    "confirmation_id": {
                        "type": "integer",
                        "description": "The confirmation ID to check.",
                    }
                },
                "required": ["confirmation_id"],
            },
        },
    },
    # Phase 6: Introspection
    {
        "type": "function",
        "function": {
            "name": "get_agent_context",
            "description": "Inspect the agent's own available tools, stored facts count, active reminders, and active plans.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    # CLI
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Execute a CLI/shell command and return its output. Use for system tasks: curl, wget, git, ls, cat, grep, find, wc, jq, python scripts, pip, node, npm, docker, etc. Destructive commands (rm, sudo, etc.) are blocked.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The shell command to execute, e.g. 'curl -s https://api.example.com/data | jq .results'",
                    },
                },
                "required": ["command"],
            },
        },
    },
]

# Conditionally add GitHub tool schemas
try:
    from config import GITHUB_TOKEN
    if GITHUB_TOKEN:
        TOOL_SCHEMAS.extend([
            {
                "type": "function",
                "function": {
                    "name": "github_list_repos",
                    "description": "List your GitHub repositories, optionally filtered by a search query.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Optional filter query."}
                        },
                        "required": [],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "github_search_issues",
                    "description": "Search issues and pull requests in a GitHub repository.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "repo": {"type": "string", "description": "Repository in owner/name format."},
                            "query": {"type": "string", "description": "Search query."},
                        },
                        "required": ["repo", "query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "github_create_issue",
                    "description": "Create a new issue in a GitHub repository.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "repo": {"type": "string", "description": "Repository in owner/name format."},
                            "title": {"type": "string", "description": "Issue title."},
                            "body": {"type": "string", "description": "Issue body/description."},
                            "labels": {"type": "string", "description": "Comma-separated label names."},
                        },
                        "required": ["repo", "title"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "github_get_pull_request",
                    "description": "Get details of a GitHub pull request.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "repo": {"type": "string", "description": "Repository in owner/name format."},
                            "pr_number": {"type": "integer", "description": "Pull request number."},
                        },
                        "required": ["repo", "pr_number"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "github_list_notifications",
                    "description": "List your unread GitHub notifications.",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "required": [],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "github_get_repo_tree",
                    "description": "List files and directories in a GitHub repository. Use this to explore a repo's structure.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "repo": {"type": "string", "description": "Repository in owner/name format."},
                            "path": {"type": "string", "description": "Path within the repo (empty for root)."},
                            "branch": {"type": "string", "description": "Branch name (default: repo default branch)."},
                        },
                        "required": ["repo"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "github_get_file_content",
                    "description": "Read the content of a file from a GitHub repository.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "repo": {"type": "string", "description": "Repository in owner/name format."},
                            "path": {"type": "string", "description": "File path within the repo."},
                            "branch": {"type": "string", "description": "Branch name (default: repo default branch)."},
                        },
                        "required": ["repo", "path"],
                    },
                },
            },
        ])
except Exception:
    pass

# Conditionally add Home Assistant tool schemas
try:
    from config import HA_URL, HA_TOKEN
    if HA_URL and HA_TOKEN:
        TOOL_SCHEMAS.extend([
            {
                "type": "function",
                "function": {
                    "name": "ha_list_entities",
                    "description": "List Home Assistant entities, optionally filtered by domain (e.g. 'light', 'switch', 'sensor').",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "domain": {"type": "string", "description": "Optional domain filter (e.g. 'light')."},
                        },
                        "required": [],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "ha_get_state",
                    "description": "Get the current state and attributes of a Home Assistant entity.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "entity_id": {"type": "string", "description": "Entity ID, e.g. 'light.living_room'."},
                        },
                        "required": ["entity_id"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "ha_call_service",
                    "description": "Call a Home Assistant service (e.g. turn on a light, set thermostat).",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "domain": {"type": "string", "description": "Service domain (e.g. 'light', 'climate')."},
                            "service": {"type": "string", "description": "Service name (e.g. 'turn_on', 'turn_off')."},
                            "entity_id": {"type": "string", "description": "Target entity ID."},
                            "data": {"type": "string", "description": "Optional JSON string with extra service data."},
                        },
                        "required": ["domain", "service", "entity_id"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "ha_get_history",
                    "description": "Get state change history for a Home Assistant entity.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "entity_id": {"type": "string", "description": "Entity ID."},
                            "hours": {"type": "integer", "description": "Hours of history to fetch (default 24)."},
                        },
                        "required": ["entity_id"],
                    },
                },
            },
        ])
except Exception:
    pass

# Conditionally add Google tool schemas
try:
    from config import GOOGLE_CLIENT_ID
    if GOOGLE_CLIENT_ID:
        TOOL_SCHEMAS.extend([
            {
                "type": "function",
                "function": {
                    "name": "gcal_list_events",
                    "description": "List upcoming Google Calendar events for the next N days.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "days": {"type": "integer", "description": "Number of days ahead (default 7)."},
                            "query": {"type": "string", "description": "Optional search query."},
                        },
                        "required": [],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "gcal_create_event",
                    "description": "Create a new Google Calendar event.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string", "description": "Event title."},
                            "start": {"type": "string", "description": "Start time (YYYY-MM-DDTHH:MM:SS or YYYY-MM-DD)."},
                            "end": {"type": "string", "description": "End time (YYYY-MM-DDTHH:MM:SS or YYYY-MM-DD)."},
                            "description": {"type": "string", "description": "Event description."},
                            "location": {"type": "string", "description": "Event location."},
                        },
                        "required": ["title", "start", "end"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "gcal_free_busy",
                    "description": "Check free/busy status for a specific date.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "date": {"type": "string", "description": "Date in YYYY-MM-DD format."},
                        },
                        "required": ["date"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "gcal_search_events",
                    "description": "Search Google Calendar events by keyword.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Search query."},
                        },
                        "required": ["query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "gmail_search",
                    "description": "Search emails using Gmail search syntax.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Search query (same syntax as Gmail search bar)."},
                            "max_results": {"type": "integer", "description": "Max results to return (default 5)."},
                        },
                        "required": ["query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "gmail_read",
                    "description": "Read the full content of an email by its message ID.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "message_id": {"type": "string", "description": "Gmail message ID."},
                        },
                        "required": ["message_id"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "gmail_send",
                    "description": "Send an email via Gmail.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "to": {"type": "string", "description": "Recipient email address."},
                            "subject": {"type": "string", "description": "Email subject."},
                            "body": {"type": "string", "description": "Email body text."},
                        },
                        "required": ["to", "subject", "body"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "gmail_create_draft",
                    "description": "Create an email draft in Gmail.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "to": {"type": "string", "description": "Recipient email address."},
                            "subject": {"type": "string", "description": "Email subject."},
                            "body": {"type": "string", "description": "Email body text."},
                        },
                        "required": ["to", "subject", "body"],
                    },
                },
            },
        ])
except Exception:
    pass
