import json
import asyncio
import inspect
import logging

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

logger = logging.getLogger(__name__)


def _get_client() -> AsyncOpenAI:
    """Build an AsyncOpenAI client pointed at the right backend."""
    if OPENWEBUI_URL and OPENWEBUI_API_KEY:
        return AsyncOpenAI(
            base_url=f"{OPENWEBUI_URL}/api",
            api_key=OPENWEBUI_API_KEY,
        )
    # Fallback: direct OpenAI
    return AsyncOpenAI(api_key=OPENAI_API_KEY)


async def _get_model(client: AsyncOpenAI) -> str:
    """Return configured model or auto-detect the first available."""
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
    """Inject stored facts into the system prompt."""
    facts = db.get_facts(chat_id)
    prompt = SYSTEM_PROMPT
    if facts:
        fact_lines = "\n".join(f"- [{f['category']}] {f['key']}: {f['value']}" for f in facts)
        prompt += f"\n\nUser facts from long-term memory:\n{fact_lines}"
    return prompt


async def _execute_tool(tool_name: str, arguments: dict, chat_id: int) -> str:
    """Execute a tool function and return its string result."""
    func = TOOL_REGISTRY.get(tool_name)
    if not func:
        return f"Unknown tool: {tool_name}"

    # Inject chat_id for tools that need it
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


async def run_agent(chat_id: int, user_content: str | list) -> str:
    """
    Main agent loop.
    user_content can be a string or a list of content blocks (for vision).
    Returns the final assistant text response.
    """
    client = _get_client()
    model = await _get_model(client)

    # Save user message to DB (store text representation)
    if isinstance(user_content, str):
        db.save_message(chat_id, "user", user_content)
    else:
        # For multi-modal content, save a text summary
        text_parts = [p["text"] for p in user_content if p.get("type") == "text"]
        db.save_message(chat_id, "user", " ".join(text_parts) if text_parts else "[media]")

    # Build messages
    system_prompt = _build_system_prompt(chat_id)
    history = db.get_history(chat_id, limit=30)

    messages = [{"role": "system", "content": system_prompt}]

    # Add history (all but the last message, which is the current one we just saved)
    if len(history) > 1:
        messages.extend(history[:-1])

    # Add current user message (may be multi-modal)
    messages.append({"role": "user", "content": user_content})

    # Agent loop
    for round_num in range(MAX_TOOL_ROUNDS):
        try:
            response = await client.chat.completions.create(
                model=model,
                messages=messages,
                tools=TOOL_SCHEMAS if TOOL_SCHEMAS else None,
            )
        except Exception as e:
            logger.error(f"LLM API error: {e}")
            return f"Sorry, I hit an error talking to the LLM: {e}"

        choice = response.choices[0]
        assistant_message = choice.message

        # If no tool calls, we're done
        if not assistant_message.tool_calls:
            reply = assistant_message.content or ""
            db.save_message(chat_id, "assistant", reply)
            return reply

        # Process tool calls
        # Append the assistant message with tool calls to context
        messages.append(assistant_message)

        for tool_call in assistant_message.tool_calls:
            fn_name = tool_call.function.name
            try:
                fn_args = json.loads(tool_call.function.arguments)
            except json.JSONDecodeError:
                fn_args = {}

            logger.info(f"Tool call: {fn_name}({fn_args})")

            result = await _execute_tool(fn_name, fn_args, chat_id)
            db.log_tool_call(chat_id, fn_name, json.dumps(fn_args), result)

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": result,
            })

    # If we exhausted rounds, return whatever we have
    try:
        response = await client.chat.completions.create(
            model=model,
            messages=messages,
        )
        reply = response.choices[0].message.content or "I ran out of tool rounds. Here's what I have so far."
    except Exception as e:
        reply = "I hit the tool round limit and encountered an error."

    db.save_message(chat_id, "assistant", reply)
    return reply
