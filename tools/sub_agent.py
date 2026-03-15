import asyncio
import json
import logging
import inspect
import time

from anthropic import AsyncAnthropic

from config import ANTHROPIC_API_KEY, CLAUDE_MODEL

logger = logging.getLogger(__name__)

MAX_ROUNDS = 10
TIMEOUT_SECONDS = 120
MAX_CONCURRENT = 3
SUB_AGENT_MODEL = CLAUDE_MODEL

# Restricted tool set for sub-agents — read-only + execution, no high-impact actions
SUB_AGENT_TOOLS = {
    "brave_search", "fetch_url", "get_current_datetime",
    "recall_facts", "semantic_recall", "execute_python",
    "think", "read_file", "write_file", "edit_file",
    "list_directory", "execute_code", "run_command",
}

_agent_sem = asyncio.Semaphore(MAX_CONCURRENT)

SYSTEM_PROMPT = (
    "You are a focused sub-agent working on a specific task. You have tools available.\n"
    "Complete the task thoroughly, then provide your final answer.\n"
    "Be concise but complete. Do not ask questions — work with what you have."
)


def _get_sub_agent_schemas() -> list[dict]:
    """Filter TOOL_SCHEMAS to only include tools available to sub-agents."""
    from tools import TOOL_SCHEMAS
    return [s for s in TOOL_SCHEMAS if s["function"]["name"] in SUB_AGENT_TOOLS]


def _openai_to_anthropic_tools(openai_schemas: list[dict]) -> list[dict]:
    """Convert OpenAI-format tool schemas to Anthropic format."""
    tools = []
    for s in openai_schemas:
        tools.append({
            "name": s["function"]["name"],
            "description": s["function"]["description"],
            "input_schema": s["function"]["parameters"],
        })
    return tools


async def _run_sub_agent(task: str, context: str, chat_id: int) -> str:
    """Run a mini agent loop: LLM → tools → LLM → ... → final answer."""
    from tools import TOOL_REGISTRY
    import db

    client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
    schemas = _get_sub_agent_schemas()
    anthropic_tools = _openai_to_anthropic_tools(schemas) if schemas else None

    user_message = task
    if context:
        user_message = f"{task}\n\nContext:\n{context}"

    messages = [
        {"role": "user", "content": user_message},
    ]

    for round_num in range(MAX_ROUNDS):
        kwargs = dict(
            model=SUB_AGENT_MODEL,
            max_tokens=4096,
            system=[{"type": "text", "text": SYSTEM_PROMPT}],
            messages=messages,
        )
        if anthropic_tools:
            kwargs["tools"] = anthropic_tools
            kwargs["tool_choice"] = {"type": "auto"}

        response = await client.messages.create(**kwargs)

        if not response or not response.content:
            return "Sub-agent received empty response from LLM."

        # Parse response
        tool_blocks = [b for b in response.content if b.type == "tool_use"]
        text_blocks = [b.text for b in response.content if b.type == "text"]

        # No tool calls — final answer
        if not tool_blocks:
            return "\n".join(text_blocks)

        # Store assistant response
        content_dicts = []
        for b in response.content:
            if b.type == "text":
                content_dicts.append({"type": "text", "text": b.text})
            elif b.type == "tool_use":
                content_dicts.append({"type": "tool_use", "id": b.id, "name": b.name, "input": b.input})
        messages.append({"role": "assistant", "content": content_dicts})

        # Process tool calls sequentially within sub-agent
        tool_results = []
        for block in tool_blocks:
            fn_name = block.name
            fn_args = block.input

            logger.info(f"Sub-agent tool: {fn_name}({fn_args})")

            func = TOOL_REGISTRY.get(fn_name)
            if not func or fn_name not in SUB_AGENT_TOOLS:
                result = f"Tool not available: {fn_name}"
            else:
                try:
                    sig = inspect.signature(func)
                    if "chat_id" in sig.parameters:
                        fn_args["chat_id"] = chat_id
                    result = func(**fn_args)
                    if asyncio.iscoroutine(result):
                        result = await result
                    result = str(result)
                except Exception as e:
                    logger.error(f"Sub-agent tool {fn_name} error: {e}")
                    result = f"Tool error: {e}"

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": result,
            })

        messages.append({"role": "user", "content": tool_results})

    # Rounds exhausted — one final no-tools call to summarize
    try:
        messages.append({
            "role": "user",
            "content": "You've used all your tool rounds. Summarize your findings so far as your final answer.",
        })
        # Merge consecutive user messages for Anthropic
        if len(messages) >= 2 and messages[-2]["role"] == "user":
            prev = messages[-2]
            last = messages.pop()
            if isinstance(prev["content"], list):
                prev["content"].append({"type": "text", "text": last["content"]})
            elif isinstance(prev["content"], str):
                prev["content"] = prev["content"] + "\n" + last["content"]

        response = await client.messages.create(
            model=SUB_AGENT_MODEL,
            max_tokens=4096,
            system=[{"type": "text", "text": SYSTEM_PROMPT}],
            messages=messages,
        )
        if response and response.content:
            text_blocks = [b.text for b in response.content if b.type == "text"]
            return "\n".join(text_blocks) if text_blocks else "Sub-agent exhausted rounds with no summary."
    except Exception as e:
        logger.error(f"Sub-agent final summary error: {e}")

    return "Sub-agent exhausted tool rounds without producing a final answer."


async def spawn_agent(task: str, context: str = "", chat_id: int = 0) -> str:
    """Spawn an independent sub-agent to work on a specific task.

    The sub-agent runs its own LLM reasoning loop with a restricted tool set.
    Multiple spawn_agent calls execute in parallel via the parent's parallel tool execution.
    """
    if not task:
        return "Error: task parameter is required."
    if not ANTHROPIC_API_KEY:
        return "Error: Anthropic API key not configured — sub-agents require API access."

    # Import here to log to parent diagnostics
    from agent import _recent_llm_calls

    start = time.time()
    logger.info(f"Spawning sub-agent: {task[:100]}")

    try:
        async with _agent_sem:
            result = await asyncio.wait_for(
                _run_sub_agent(task, context, chat_id),
                timeout=TIMEOUT_SECONDS,
            )
    except asyncio.TimeoutError:
        elapsed = time.time() - start
        logger.warning(f"Sub-agent timed out after {elapsed:.1f}s: {task[:100]}")
        result = f"Sub-agent timed out after {TIMEOUT_SECONDS}s. The task may have been too complex."
    except Exception as e:
        logger.error(f"Sub-agent error: {e}", exc_info=True)
        result = f"Sub-agent error: {e}"

    elapsed = time.time() - start
    _recent_llm_calls.append({
        "time": time.strftime("%H:%M:%S"),
        "status": "sub-agent",
        "model": SUB_AGENT_MODEL,
        "task": task[:200],
        "elapsed": f"{elapsed:.1f}s",
        "result_length": len(result),
    })

    logger.info(f"Sub-agent completed in {elapsed:.1f}s ({len(result)} chars)")
    return result
