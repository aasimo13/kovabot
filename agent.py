import copy
import json
import asyncio
import inspect
import logging
import time
from collections import deque

from anthropic import AsyncAnthropic

import db
from config import (
    ANTHROPIC_API_KEY,
    CLAUDE_MODEL,
    MODEL_ID,
    MAX_TOOL_ROUNDS,
    SYSTEM_PROMPT,
)
from tools import TOOL_REGISTRY, TOOL_SCHEMAS
from tools.code_exec import execute_custom_tool

logger = logging.getLogger(__name__)

# Store recent LLM call diagnostics for /diagnostics command
_recent_llm_calls: deque[dict] = deque(maxlen=10)

# Lock for status callback to prevent concurrent Telegram message edits
_status_lock = asyncio.Lock()

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
    "spawn_agent": "Running sub-agent",
}


def _get_client() -> AsyncAnthropic:
    return AsyncAnthropic(api_key=ANTHROPIC_API_KEY)


def _get_model() -> str:
    if MODEL_ID:
        return MODEL_ID
    db_model = db.get_setting("claude_model", "")
    return db_model if db_model else CLAUDE_MODEL


def _openai_to_anthropic_tools(openai_schemas: list[dict]) -> list[dict]:
    """Convert OpenAI-format tool schemas to Anthropic format."""
    tools = []
    for s in openai_schemas:
        tools.append({
            "name": s["function"]["name"],
            "description": s["function"]["description"],
            "input_schema": s["function"]["parameters"],
        })
    # Enable prompt caching on last tool
    if tools:
        tools[-1]["cache_control"] = {"type": "ephemeral"}
    return tools


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


async def _execute_tools_parallel(tool_blocks, chat_id: int, status_callback=None) -> list[dict]:
    """Execute multiple tool-use blocks concurrently via asyncio.gather.
    Returns list of tool_result dicts for inclusion in a user message."""
    sem = asyncio.Semaphore(5)

    async def _run_one(block):
        fn_name = block["name"]
        fn_args = block["input"]

        logger.info(f"Tool call: {fn_name}({fn_args})")

        if status_callback:
            label = TOOL_STATUS_LABELS.get(fn_name, f"Using {fn_name}")
            async with _status_lock:
                await status_callback(f"{label}...")

        async with sem:
            try:
                result = await _execute_tool(fn_name, fn_args, chat_id)
            except Exception as e:
                logger.error(f"Parallel tool {fn_name} error: {e}")
                result = f"Tool error: {e}"

        if fn_name != "think":
            db.log_tool_call(chat_id, fn_name, json.dumps(fn_args), result)

        return {
            "type": "tool_result",
            "tool_use_id": block["id"],
            "content": result,
        }

    tasks = [_run_one(b) for b in tool_blocks]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Convert any unexpected exceptions to error messages
    tool_results = []
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tool_blocks[i]["id"],
                "content": f"Tool error: {r}",
            })
        else:
            tool_results.append(r)
    return tool_results


DEVELOPER_TOOLS = {"run_command", "execute_python", "read_file", "write_file", "edit_file", "list_directory", "execute_code", "spawn_agent"}


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


def _sanitize_messages(messages: list[dict]) -> list[dict]:
    """Clean messages for Anthropic API compatibility.
    - Removes system messages (handled separately via system= parameter)
    - Ensures strict alternating user/assistant order
    - Normalizes content formats
    """
    cleaned = []
    for msg in messages:
        role = msg.get("role")
        if role == "system":
            continue
        content = msg.get("content")
        if role == "user" and not content:
            content = ""
        if role == "assistant" and not content:
            continue
        cleaned.append({"role": role, "content": content})

    # Enforce strict alternating by merging consecutive same-role messages
    merged = []
    for msg in cleaned:
        if merged and merged[-1]["role"] == msg["role"]:
            prev = merged[-1]
            # Merge content
            prev_content = prev["content"]
            new_content = msg["content"]
            if isinstance(prev_content, str) and isinstance(new_content, str):
                prev["content"] = prev_content + "\n" + new_content
            elif isinstance(prev_content, list) and isinstance(new_content, list):
                prev["content"] = prev_content + new_content
            elif isinstance(prev_content, str) and isinstance(new_content, list):
                prev["content"] = [{"type": "text", "text": prev_content}] + new_content
            elif isinstance(prev_content, list) and isinstance(new_content, str):
                prev["content"] = prev_content + [{"type": "text", "text": new_content}]
        else:
            merged.append(dict(msg))

    # Ensure first message is from user
    if merged and merged[0]["role"] != "user":
        merged.insert(0, {"role": "user", "content": ""})

    return merged


async def _call_llm(client, model, system_prompt, messages, use_tools=True):
    """Call the Anthropic Messages API with tool support and retry logic."""
    effective_schemas = _get_effective_tool_schemas() if use_tools else []
    anthropic_tools = _openai_to_anthropic_tools(effective_schemas) if effective_schemas else None

    # System prompt with caching
    system = [{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}]

    clean_messages = _sanitize_messages(messages)

    last_error = None
    for attempt in range(2):
        try:
            kwargs = dict(
                model=model,
                max_tokens=4096,
                system=system,
                messages=clean_messages,
            )
            if anthropic_tools:
                kwargs["tools"] = anthropic_tools
                kwargs["tool_choice"] = {"type": "auto"}

            logger.info(
                f"LLM call attempt {attempt + 1}/2, model={model}, "
                f"{len(effective_schemas)} tools, {len(clean_messages)} messages"
            )

            response = await client.messages.create(**kwargs)

            # Parse response for diagnostics
            tool_blocks = [b for b in response.content if b.type == "tool_use"]
            text_blocks = [b for b in response.content if b.type == "text"]
            tool_names = [b.name for b in tool_blocks]

            logger.info(
                f"LLM response OK: tool_calls={bool(tool_blocks)}, "
                f"content={bool(text_blocks)}, tools_used={tool_names}"
            )
            _recent_llm_calls.append({
                "time": time.strftime("%H:%M:%S"),
                "status": "ok",
                "backend": "anthropic",
                "model": model,
                "tools_offered": len(effective_schemas),
                "tool_calls": tool_names,
                "has_content": bool(text_blocks),
                "attempt": attempt + 1,
            })
            return response
        except Exception as e:
            last_error = str(e)
            logger.error(f"LLM error (attempt {attempt + 1}): {e}", exc_info=True)
        if attempt == 0:
            await asyncio.sleep(1)

    _recent_llm_calls.append({
        "time": time.strftime("%H:%M:%S"),
        "status": "FAILED",
        "backend": "anthropic",
        "model": model,
        "tools_offered": len(effective_schemas),
        "error": last_error,
    })
    logger.error(f"LLM FAILED after 2 attempts: {last_error}")

    # Fallback: try without tools
    logger.warning("Falling back to no-tools LLM call")
    response = await client.messages.create(
        model=model,
        max_tokens=4096,
        system=system,
        messages=clean_messages,
    )
    _recent_llm_calls.append({
        "time": time.strftime("%H:%M:%S"),
        "status": "fallback",
        "backend": "anthropic",
        "model": model,
        "reason": "tools failed",
    })
    return response


def _response_to_content_dicts(response) -> list[dict]:
    """Convert Anthropic response content blocks to serializable dicts."""
    content = []
    for block in response.content:
        if block.type == "text":
            content.append({"type": "text", "text": block.text})
        elif block.type == "tool_use":
            content.append({"type": "tool_use", "id": block.id, "name": block.name, "input": block.input})
    return content


async def run_agent(chat_id: int, user_content: str | list, status_callback=None) -> str:
    """
    Main agent loop.
    user_content: string or list of content blocks (for vision).
    status_callback: async function(status_text) called during tool execution.
    Returns the final assistant text response.
    """
    client = _get_client()
    model = _get_model()

    # Save user message to DB
    if isinstance(user_content, str):
        db.save_message(chat_id, "user", user_content)
    else:
        text_parts = [p["text"] for p in user_content if p.get("type") == "text"]
        db.save_message(chat_id, "user", " ".join(text_parts) if text_parts else "[media]")

    # Build messages — system prompt is separate in Anthropic
    system_prompt = _build_system_prompt(chat_id)
    history = db.get_history(chat_id, limit=30)

    messages = []
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
            response = await _call_llm(client, model, system_prompt, messages)
        except Exception as e:
            logger.error(f"LLM API error: {e}")
            return f"Sorry, I hit an error: {e}"

        if response is None or not response.content:
            return "Sorry, I couldn't get a response."

        # Parse response content blocks
        tool_blocks = [
            {"id": b.id, "name": b.name, "input": b.input}
            for b in response.content if b.type == "tool_use"
        ]
        text_blocks = [b.text for b in response.content if b.type == "text"]

        # No tool calls — we have the final answer
        if not tool_blocks:
            reply = "\n".join(text_blocks)
            db.save_message(chat_id, "assistant", reply)
            asyncio.create_task(_maybe_summarize(client, model, system_prompt, chat_id))
            return reply

        # Store assistant response with tool use blocks, then process tools
        messages.append({"role": "assistant", "content": _response_to_content_dicts(response)})
        tool_results = await _execute_tools_parallel(tool_blocks, chat_id, status_callback)
        messages.append({"role": "user", "content": tool_results})

    # Exhausted tool rounds — get final answer without tools
    try:
        response = await client.messages.create(
            model=model,
            max_tokens=4096,
            system=[{"type": "text", "text": system_prompt}],
            messages=_sanitize_messages(messages),
        )
        text_blocks = [b.text for b in response.content if b.type == "text"]
        reply = "\n".join(text_blocks) if text_blocks else "I ran out of steps but here's what I found."
    except Exception as e:
        reply = "I hit the tool round limit and encountered an error."

    db.save_message(chat_id, "assistant", reply)
    return reply


async def _maybe_summarize(client, model, system_prompt, chat_id: int):
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

        response = await client.messages.create(
            model=model,
            max_tokens=300,
            system=[{"type": "text", "text": "Summarize this conversation excerpt in 3-5 sentences. Preserve key facts, decisions, and context. Be concise."}],
            messages=[
                {"role": "user", "content": f"Previous summary:\n{existing_summary}\n\nNew messages:\n{text_block}"},
            ],
        )
        if response and response.content:
            text_blocks = [b.text for b in response.content if b.type == "text"]
            summary = "\n".join(text_blocks)
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
