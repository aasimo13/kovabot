import json
import logging

import db

logger = logging.getLogger(__name__)


async def create_plan(title: str, steps: str, chat_id: int = 0) -> str:
    """Create a multi-step plan. Steps can be a JSON array or newline-separated text."""
    try:
        # Parse steps
        try:
            step_list = json.loads(steps)
            if not isinstance(step_list, list):
                step_list = [str(step_list)]
        except (json.JSONDecodeError, TypeError):
            step_list = [s.strip() for s in steps.strip().split("\n") if s.strip()]

        if not step_list:
            return "Error: No steps provided."

        structured_steps = []
        for i, step in enumerate(step_list):
            if isinstance(step, dict):
                structured_steps.append({
                    "index": i,
                    "description": step.get("description", str(step)),
                    "status": "pending",
                    "result": "",
                })
            else:
                structured_steps.append({
                    "index": i,
                    "description": str(step),
                    "status": "pending",
                    "result": "",
                })

        plan_id = db.create_plan(chat_id, title, structured_steps)

        lines = [f"Plan created: **{title}** (ID: {plan_id})"]
        for s in structured_steps:
            lines.append(f"  {s['index'] + 1}. [ ] {s['description']}")
        return "\n".join(lines)
    except Exception as e:
        logger.error(f"create_plan error: {e}")
        return f"Error creating plan: {e}"


async def update_plan_step(plan_id: int, step_index: int, status: str, result: str = "", chat_id: int = 0) -> str:
    """Update the status and result of a plan step. Status: pending, in_progress, completed, failed."""
    try:
        plan = db.get_plan(plan_id)
        if not plan:
            return f"Plan #{plan_id} not found."

        steps = plan["steps"]
        if step_index < 0 or step_index >= len(steps):
            return f"Step index {step_index} is out of range (0-{len(steps) - 1})."

        steps[step_index]["status"] = status
        if result:
            steps[step_index]["result"] = result

        # Check if all steps are done
        all_done = all(s["status"] in ("completed", "failed") for s in steps)
        plan_status = "completed" if all_done else "active"

        db.update_plan(plan_id, steps, plan_status)

        step = steps[step_index]
        icon = {"pending": "[ ]", "in_progress": "[~]", "completed": "[x]", "failed": "[!]"}.get(status, "[ ]")
        return f"Step {step_index + 1} updated: {icon} {step['description']} -> {status}"
    except Exception as e:
        logger.error(f"update_plan_step error: {e}")
        return f"Error updating plan step: {e}"


async def get_plan(plan_id: int, chat_id: int = 0) -> str:
    """Get the current status of a plan with all steps."""
    try:
        plan = db.get_plan(plan_id)
        if not plan:
            return f"Plan #{plan_id} not found."

        lines = [f"**{plan['title']}** (ID: {plan_id}, Status: {plan['status']})"]
        for s in plan["steps"]:
            icon = {"pending": "[ ]", "in_progress": "[~]", "completed": "[x]", "failed": "[!]"}.get(s["status"], "[ ]")
            line = f"  {s['index'] + 1}. {icon} {s['description']}"
            if s.get("result"):
                line += f"\n       Result: {s['result'][:200]}"
            lines.append(line)

        completed = sum(1 for s in plan["steps"] if s["status"] == "completed")
        total = len(plan["steps"])
        lines.append(f"\nProgress: {completed}/{total} steps completed")
        return "\n".join(lines)
    except Exception as e:
        logger.error(f"get_plan error: {e}")
        return f"Error getting plan: {e}"
