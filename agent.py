import copy
import json
import asyncio
import inspect
import logging
import time
from collections import deque

from openai import AsyncOpenAI

import db
from config import (
    OPENWEBUI_URL,
    OPENWEBUI_API_KEY,
    OPENAI_API_KEY,
    MODEL_ID,
    MAX_TOOL_ROUNDS,
    SYSTEM_PROMPT,
)
from tools import TOOL_REGISTRY, TOOL_SCHEMAS
from tools.code_exec import execute_custom_tool

logger = logging.getLogger(__name__)

# Store recent LLM call diagnostics for /diagnostics command
_recent_llm_calls: deque[dict] = deque(maxlen=10)

TOOL_STATUS_LABELS = {
    "brave_search": "Searching the web",
    "store_fact": "Saving to memory",
    "recall_facts": "Checking memory",
    "create_reminder": "Setting reminder",
    "list_reminders": "Checking reminders",
    "cancel_reminder": "Cancelling reminder",
    "execute_python": "Running code",
    "get_current_datetime": "Checking the time",
    "fetch_url": "Reading webpage",
    "generate_file": "Creating file",
    # Phase 1
    "text_to_speech": "Generating voice",
    # Phase 2
    "github_list_repos": "Listing repos",
    "github_search_issues": "Searching issues",
    "github_create_issue": "Creating issue",
    "github_get_pull_request": "Getting PR details",
    "github_list_notifications": "Checking notifications",
    "github_get_repo_tree": "Browsing repo",
    "github_get_file_content": "Reading file",
    "ha_list_entities": "Listing devices",
    "ha_get_state": "Checking device state",
    "ha_call_service": "Controlling device",
    "ha_get_history": "Getting device history",
    # Phase 3
    "gcal_list_events": "Checking calendar",
    "gcal_create_event": "Creating event",
    "gcal_free_busy": "Checking availability",
    "gcal_search_events": "Searching calendar",
    "gmail_search": "Searching email",
    "gmail_read": "Reading email",
    "gmail_send": "Sending email",
    "gmail_create_draft": "Creating draft",
    # Phase 5
    "semantic_recall": "Searching memory",
    # Phase 6
    "create_plan": "Creating plan",
    "update_plan_step": "Updating plan",
    "get_plan": "Checking plan",
    "request_confirmation": "Requesting confirmation",
    "check_confirmation": "Checking confirmation",
    "get_agent_context": "Inspecting context",
    "run_command": "Running command",
    "think": "Thinking",
    "deep_research": "Researching in depth",
    # Coding Agent
    "read_file": "Reading file",
    "write_file": "Writing file",
    "edit_file": "Editing file",
    "list_directory": "Listing workspace",
    "execute_code": "Running code",
}


def _get_client() -> AsyncOpenAI:
    if OPENWEBUI_URL and OPENWEBUI_API_KEY:
        return AsyncOpenAI(
            base_url=f"{OPENWEBUI_URL}/api",
            api_key=OPENWEBUI_API_KEY,
        )
    return AsyncOpenAI(api_key=OPENAI_API_KEY)


def _get_tool_client() -> tuple[AsyncOpenAI, str]:
    """Get a client suitable for tool-calling requests.
    Open WebUI often doesn't support the tools parameter properly,
    so use OpenAI directly when available."""
    if OPENAI_API_KEY:
        return AsyncOpenAI(api_key=OPENAI_API_KEY), "openai"
    if OPENWEBUI_URL and OPENWEBUI_API_KEY:
        return AsyncOpenAI(
            base_url=f"{OPENWEBUI_URL}/api",
            api_key=OPENWEBUI_API_KEY,
        ), "openwebui"
    return AsyncOpenAI(api_key=OPENAI_API_KEY), "openai"


async def _get_model(client: AsyncOpenAI) -> str:
    if MODEL_ID:
        return MODEL_ID
    try:
        models = await client.models.list()
        if models.data:
            return models.data[0].id
    except Exception as e:
        logger.error(f"Error fetching models: {e}")
    return "gpt-4o"


def _build_system_prompt(chat_id: int) -> str:
    facts = db.get_facts(chat_id)
    summary = db.get_conversation_summary(chat_id)

    # Always use config.py as the base prompt.
    # DB "system_prompt_extra" can append additional instructions, but never override.
    prompt = SYSTEM_PROMPT
    extra = db.get_setting("system_prompt_extra", "")
    if extra.strip():
        prompt += f"\n\nAdditional instructions:\n{extra}"

    if facts:
        fact_lines = "\n".join(f"- [{f['category']}] {f['key']}: {f['value']}" for f in facts)
        prompt += f"\n\nUser facts from long-term memory:\n{fact_lines}"

    if summary:
        prompt += f"\n\nSummary of earlier conversation:\n{summary}"

    logger.debug(f"System prompt: {len(prompt)} chars, {len(facts) if facts else 0} facts, summary={'yes' if summary else 'no'}")
    return prompt


async def _execute_tool(tool_name: str, arguments: dict, chat_id: int) -> str:
    func = TOOL_REGISTRY.get(tool_name)
    if func:
        sig = inspect.signature(func)
        if "chat_id" in sig.parameters:
            arguments["chat_id"] = chat_id

        try:
            result = func(**arguments)
            if asyncio.iscoroutine(result):
                result = await result
            return str(result)
        except Exception as e:
            logger.error(f"Tool {tool_name} error: {e}")
            return f"Tool error: {e}"

    # Check custom tools
    custom = db.get_custom_tool_by_name(tool_name)
    if custom and custom["enabled"]:
        try:
            result = await execute_custom_tool(custom["code_body"], arguments)
            return result
        except Exception as e:
            logger.error(f"Custom tool {tool_name} error: {e}")
            return f"Custom tool error: {e}"

    return f"Unknown tool: {tool_name}"


DEVELOPER_TOOLS = {"run_command", "execute_python", "read_file", "write_file", "edit_file", "list_directory", "execute_code"}


def _get_effective_tool_schemas() -> list[dict]:
    """Return TOOL_SCHEMAS filtered by tool_overrides (disabled tools removed, descriptions overridden), plus custom tools."""
    overrides = db.get_tool_overrides()
    dev_mode = db.get_setting("developer_mode", "false") == "true"

    effective = []
    for schema in TOOL_SCHEMAS:
        name = schema["function"]["name"]
        # Developer tools require developer_mode
        if name in DEVELOPER_TOOLS and not dev_mode:
            continue
        override = overrides.get(name)
        if override and not override["enabled"]:
            continue
        if override and override.get("description_override"):
            schema = copy.deepcopy(schema)
            schema["function"]["description"] = override["description_override"]
        effective.append(schema)

    # Append enabled custom tools
    for tool in db.get_custom_tools(enabled_only=True):
        properties = {}
        required = []
        for param in tool["parameters"]:
            properties[param["name"]] = {
                "type": param.get("type", "string"),
                "description": param.get("description", ""),
            }
            if param.get("required"):
                required.append(param["name"])

        effective.append({
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool["description"],
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        })

    return effective


def _sanitize_messages(messages: list[dict], strip_tool_messages: bool = False) -> list[dict]:
    """Clean messages for API compatibility.
    - Ensures all messages have valid content
    - Optionally strips tool_calls and tool-role messages (for no-tools fallback)
    """
    cleaned = []
    for msg in messages:
        # Skip tool-result messages when falling back to no-tools
        if strip_tool_messages and msg.get("role") == "tool":
            continue

        # Handle assistant messages that are response objects (not dicts)
        if hasattr(msg, "role"):
            # This is a ChatCompletionMessage object, convert to dict
            d = {"role": msg.role}
            if msg.content:
                d["content"] = msg.content
            if not strip_tool_messages and hasattr(msg, "tool_calls") and msg.tool_calls:
                d["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                    }
                    for tc in msg.tool_calls
                ]
            elif strip_tool_messages:
                # Strip tool_calls from assistant messages, keep only content
                if not msg.content:
                    d["content"] = "(internal processing)"
                # Skip this message entirely if it was only a tool call with no text
                if not msg.content and hasattr(msg, "tool_calls") and msg.tool_calls:
                    continue
            cleaned.append(d)
            continue

        # Regular dict message
        m = dict(msg)
        if strip_tool_messages:
            m.pop("tool_calls", None)
            if m.get("role") == "assistant" and not m.get("content"):
                continue  # Skip empty assistant messages that only had tool_calls

        # Ensure content is present (OpenAI rejects null content on some roles)
        if m.get("role") in ("user", "system") and not m.get("content"):
            m["content"] = ""

        cleaned.append(m)

    return cleaned


async def _call_llm(client, model, messages, use_tools=True):
    """Call the LLM with robust tool support.

    Strategy:
    1. Try with tools via OpenAI direct (with retry)
    2. If tools fail, fall back to OpenAI direct WITHOUT tools (not Open WebUI)
    3. Never silently swallow errors — log everything clearly
    """
    effective_schemas = _get_effective_tool_schemas() if use_tools else []

    if use_tools and effective_schemas:
        tool_client, tool_backend = _get_tool_client()
        # Use a known tool-capable model when going direct to OpenAI
        tool_model = model if tool_backend != "openai" else (model if model.startswith("gpt") else "gpt-4o")
        clean_messages = _sanitize_messages(messages, strip_tool_messages=False)

        last_error = None
        for attempt in range(2):
            try:
                logger.info(
                    f"Tool call attempt {attempt + 1}/2 via {tool_backend}, "
                    f"model={tool_model}, {len(effective_schemas)} tools, "
                    f"{len(clean_messages)} messages"
                )
                response = await tool_client.chat.completions.create(
                    model=tool_model,
                    messages=clean_messages,
                    tools=effective_schemas,
                    tool_choice="auto",
                )
                if response is not None and response.choices:
                    msg = response.choices[0].message
                    has_tools = bool(msg.tool_calls) if msg else False
                    tool_names = [tc.function.name for tc in (msg.tool_calls or [])] if has_tools else []
                    logger.info(
                        f"LLM response OK: tool_calls={has_tools}, "
                        f"content={bool(msg.content) if msg else False}, "
                        f"tools_used={tool_names}"
                    )
                    _recent_llm_calls.append({
                        "time": time.strftime("%H:%M:%S"),
                        "status": "ok",
                        "backend": tool_backend,
                        "model": tool_model,
                        "tools_offered": len(effective_schemas),
                        "tool_calls": tool_names,
                        "has_content": bool(msg.content) if msg else False,
                        "attempt": attempt + 1,
                    })
                    return response
                last_error = "empty response (no choices)"
                logger.warning(f"Tool LLM returned empty (attempt {attempt + 1})")
            except Exception as e:
                last_error = str(e)
                logger.error(
                    f"Tool LLM error (attempt {attempt + 1}, "
                    f"backend={tool_backend}, model={tool_model}): {e}",
                    exc_info=True,
                )
            # Brief pause before retry
            if attempt == 0:
                await asyncio.sleep(1)

        _recent_llm_calls.append({
            "time": time.strftime("%H:%M:%S"),
            "status": "FAILED",
            "backend": tool_backend,
            "model": tool_model,
            "tools_offered": len(effective_schemas),
            "error": last_error,
        })
        logger.error(f"Tool calling FAILED after 2 attempts: {last_error}")

    # Fallback: use the best available client even without tools.
    # Prefer OpenAI direct over Open WebUI for response quality.
    if OPENAI_API_KEY:
        fallback_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
        fallback_model = model if model.startswith("gpt") else "gpt-4o"
        fallback_label = "openai-direct"
    else:
        fallback_client = client
        fallback_model = model
        fallback_label = "primary"

    # Strip tool messages from history (no-tools endpoint rejects them)
    fallback_messages = _sanitize_messages(messages, strip_tool_messages=True)

    logger.warning(
        f"Falling back to no-tools LLM call via {fallback_label}, "
        f"model={fallback_model}, {len(fallback_messages)} messages"
    )
    response = await fallback_client.chat.completions.create(
        model=fallback_model,
        messages=fallback_messages,
    )
    _recent_llm_calls.append({
        "time": time.strftime("%H:%M:%S"),
        "status": "fallback",
        "backend": fallback_label,
        "model": fallback_model,
        "reason": "tools failed or disabled",
    })
    return response


async def run_agent(chat_id: int, user_content: str | list, status_callback=None) -> str:
    """
    Main agent loop.
    user_content: string or list of content blocks (for vision).
    status_callback: async function(status_text) called during tool execution.
    Returns the final assistant text response.
    """
    client = _get_client()
    model = await _get_model(client)

    # Save user message to DB
    if isinstance(user_content, str):
        db.save_message(chat_id, "user", user_content)
    else:
        text_parts = [p["text"] for p in user_content if p.get("type") == "text"]
        db.save_message(chat_id, "user", " ".join(text_parts) if text_parts else "[media]")

    # Build messages
    system_prompt = _build_system_prompt(chat_id)
    history = db.get_history(chat_id, limit=30)

    messages = [{"role": "system", "content": system_prompt}]
    if len(history) > 1:
        messages.extend(history[:-1])
    messages.append({"role": "user", "content": user_content})

    # Read max rounds from settings (DB overrides config)
    max_rounds_str = db.get_setting("max_tool_rounds", str(MAX_TOOL_ROUNDS))
    try:
        base_rounds = int(max_rounds_str)
    except ValueError:
        base_rounds = MAX_TOOL_ROUNDS
    active_plans = db.get_active_plans(chat_id)
    max_rounds = base_rounds + 5 if active_plans else base_rounds

    # Agent loop
    for round_num in range(max_rounds):
        try:
            response = await _call_llm(client, model, messages)
        except Exception as e:
            logger.error(f"LLM API error: {e}")
            return f"Sorry, I hit an error: {e}"

        if response is None or not response.choices:
            return "Sorry, I couldn't get a response."

        choice = response.choices[0]
        assistant_message = choice.message

        # No tool calls — we have the final answer
        if not assistant_message.tool_calls:
            reply = assistant_message.content or ""
            db.save_message(chat_id, "assistant", reply)
            # Trigger summarization check in background
            asyncio.create_task(_maybe_summarize(client, model, chat_id))
            return reply

        # Process tool calls
        messages.append(assistant_message)

        for tool_call in assistant_message.tool_calls:
            fn_name = tool_call.function.name
            try:
                fn_args = json.loads(tool_call.function.arguments)
            except json.JSONDecodeError:
                fn_args = {}

            logger.info(f"Tool call: {fn_name}({fn_args})")

            # Send status update
            if status_callback:
                label = TOOL_STATUS_LABELS.get(fn_name, f"Using {fn_name}")
                await status_callback(f"{label}...")

            result = await _execute_tool(fn_name, fn_args, chat_id)
            # Don't log internal reasoning to tool call history
            if fn_name != "think":
                db.log_tool_call(chat_id, fn_name, json.dumps(fn_args), result)

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": result,
            })

    # Exhausted tool rounds — get final answer without tools
    try:
        response = await client.chat.completions.create(
            model=model,
            messages=messages,
        )
        reply = response.choices[0].message.content or "I ran out of steps but here's what I found."
    except Exception as e:
        reply = "I hit the tool round limit and encountered an error."

    db.save_message(chat_id, "assistant", reply)
    return reply


async def _maybe_summarize(client, model, chat_id: int):
    """Summarize older messages if conversation is getting long."""
    try:
        msg_count = db.get_message_count(chat_id)
        if msg_count < 40:
            return

        # Get older messages (beyond the recent 20)
        old_messages = db.get_history_with_offset(chat_id, limit=50, offset=20)
        if len(old_messages) < 10:
            return

        existing_summary = db.get_conversation_summary(chat_id) or ""
        text_block = "\n".join(f"{m['role']}: {m['content']}" for m in old_messages[:20])

        summary_prompt = [
            {"role": "system", "content": "Summarize this conversation excerpt in 3-5 sentences. Preserve key facts, decisions, and context. Be concise."},
            {"role": "user", "content": f"Previous summary:\n{existing_summary}\n\nNew messages:\n{text_block}"},
        ]

        response = await client.chat.completions.create(
            model=model,
            messages=summary_prompt,
            max_tokens=300,
        )
        if response and response.choices:
            summary = response.choices[0].message.content
            db.save_conversation_summary(chat_id, summary)
            # Clean up old messages that have been summarized
            db.trim_old_messages(chat_id, keep_recent=30)

            # Embed the summary for semantic search (Phase 5)
            try:
                from embeddings import get_embedding
                embedding = await get_embedding(summary)
                db.save_memory_vector(chat_id, "summary", f"summary_{chat_id}", summary, embedding)
            except Exception as e:
                logger.debug(f"Summary embedding skipped: {e}")
    except Exception as e:
        logger.error(f"Summarization error: {e}")
