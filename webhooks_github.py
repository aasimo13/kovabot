import logging
from webhooks import register_channel

logger = logging.getLogger(__name__)


@register_channel("github")
async def handle_github_webhook(chat_id: int, payload: dict) -> str:
    """Parse GitHub webhook events (push, PR, issues)."""
    action = payload.get("action", "")
    event_parts = []

    # Push event
    if "commits" in payload and "ref" in payload:
        ref = payload["ref"].replace("refs/heads/", "")
        repo = payload.get("repository", {}).get("full_name", "unknown")
        commits = payload.get("commits", [])
        event_parts.append(f"Push to **{repo}** ({ref}): {len(commits)} commit(s)")
        for c in commits[:5]:
            msg = c.get("message", "").split("\n")[0]
            event_parts.append(f"  - `{c['id'][:7]}` {msg}")

    # Pull request event
    elif "pull_request" in payload:
        pr = payload["pull_request"]
        repo = payload.get("repository", {}).get("full_name", "unknown")
        event_parts.append(f"PR {action} in **{repo}**: #{pr['number']} {pr['title']}")
        event_parts.append(f"  {pr.get('html_url', '')}")

    # Issue event
    elif "issue" in payload:
        issue = payload["issue"]
        repo = payload.get("repository", {}).get("full_name", "unknown")
        event_parts.append(f"Issue {action} in **{repo}**: #{issue['number']} {issue['title']}")
        event_parts.append(f"  {issue.get('html_url', '')}")

    else:
        event_parts.append(f"GitHub event: {action or 'unknown'}")

    return "\n".join(event_parts) if event_parts else "GitHub webhook received."
