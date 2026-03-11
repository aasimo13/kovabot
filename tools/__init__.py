from tools.datetime_tools import get_current_datetime
from tools.web_search import brave_search
from tools.memory import store_fact, recall_facts
from tools.reminders import create_reminder, list_reminders, cancel_reminder
from tools.code_exec import execute_python

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
}

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
]
