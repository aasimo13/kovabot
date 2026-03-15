import asyncio
import json
import logging
import time

from openai import AsyncOpenAI

from config import OPENAI_API_KEY

logger = logging.getLogger(__name__)

MAX_ROUNDS = 10
TIMEOUT_SECONDS = 120
MAX_CONCURRENT = 3
SUB_AGENT_MODEL = "gpt-4o-mini"

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


async def _run_sub_agent(task: str, context: str, chat_id: int) -> str:
    """Run a mini agent loop: LLM → tools → LLM → ... → final answer."""
    from tools import TOOL_REGISTRY
    import inspect
    import db

    client = AsyncOpenAI(api_key=OPENAI_API_KEY)
    schemas = _get_sub_agent_schemas()

    user_message = task
    if context:
        user_message = f"{task}\n\nContext:\n{context}"

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]

    for round_num in range(MAX_ROUNDS):
        response = await client.chat.completions.create(
            model=SUB_AGENT_MODEL,
            messages=messages,
            tools=schemas if schemas else None,
            tool_choice="auto" if schemas else None,
        )

        if not response or not response.choices:
            return "Sub-agent received empty response from LLM."

        msg = response.choices[0].message

        # No tool calls — final answer
        if not msg.tool_calls:
            return msg.content or ""

        # Process tool calls sequentially within sub-agent
        messages.append(msg)
        for tool_call in msg.tool_calls:
            fn_name = tool_call.function.name
            try:
                fn_args = json.loads(tool_call.function.arguments)
            except json.JSONDecodeError:
                fn_args = {}

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

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": result,
            })

    # Rounds exhausted — one final no-tools call to summarize
    try:
        messages.append({
            "role": "user",
            "content": "You've used all your tool rounds. Summarize your findings so far as your final answer.",
        })
        response = await client.chat.completions.create(
            model=SUB_AGENT_MODEL,
            messages=messages,
        )
        if response and response.choices:
            return response.choices[0].message.content or "Sub-agent exhausted rounds with no summary."
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
    if not OPENAI_API_KEY:
        return "Error: OpenAI API key not configured — sub-agents require direct OpenAI access."

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
