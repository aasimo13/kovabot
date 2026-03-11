import json
import logging

import aiohttp

from config import GITHUB_TOKEN

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"
HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}


def _auth_headers() -> dict:
    h = dict(HEADERS)
    if GITHUB_TOKEN:
        h["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    return h


async def github_list_repos(query: str = "", chat_id: int = 0) -> str:
    """List authenticated user's repositories, optionally filtered by query."""
    try:
        async with aiohttp.ClientSession() as session:
            url = f"{GITHUB_API}/user/repos?sort=updated&per_page=20"
            async with session.get(url, headers=_auth_headers(), timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    return f"GitHub API error: {resp.status}"
                repos = await resp.json()

        if query:
            q = query.lower()
            repos = [r for r in repos if q in r["full_name"].lower() or q in (r.get("description") or "").lower()]

        if not repos:
            return "No repositories found."

        lines = []
        for r in repos[:20]:
            stars = r.get("stargazers_count", 0)
            desc = r.get("description") or ""
            lang = r.get("language") or ""
            lines.append(f"- **{r['full_name']}** ({lang}) - {desc} [{stars} stars]")
        return "\n".join(lines)
    except Exception as e:
        logger.error(f"github_list_repos error: {e}")
        return f"Error listing repos: {e}"


async def github_search_issues(repo: str, query: str, chat_id: int = 0) -> str:
    """Search issues and PRs in a repository."""
    try:
        async with aiohttp.ClientSession() as session:
            search_q = f"{query} repo:{repo}"
            url = f"{GITHUB_API}/search/issues?q={search_q}&per_page=10"
            async with session.get(url, headers=_auth_headers(), timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    return f"GitHub API error: {resp.status}"
                data = await resp.json()

        items = data.get("items", [])
        if not items:
            return f"No issues/PRs found matching '{query}' in {repo}."

        lines = []
        for item in items[:10]:
            kind = "PR" if "pull_request" in item else "Issue"
            state = item["state"]
            lines.append(f"- [{kind}] #{item['number']} {item['title']} ({state}) — {item['html_url']}")
        return "\n".join(lines)
    except Exception as e:
        logger.error(f"github_search_issues error: {e}")
        return f"Error searching issues: {e}"


async def github_create_issue(repo: str, title: str, body: str = "", labels: str = "", chat_id: int = 0) -> str:
    """Create a new issue in a repository."""
    try:
        payload = {"title": title, "body": body}
        if labels:
            payload["labels"] = [l.strip() for l in labels.split(",")]

        async with aiohttp.ClientSession() as session:
            url = f"{GITHUB_API}/repos/{repo}/issues"
            async with session.post(url, headers=_auth_headers(), json=payload, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status not in (200, 201):
                    err = await resp.text()
                    return f"GitHub API error: {resp.status} — {err[:200]}"
                issue = await resp.json()

        return f"Issue #{issue['number']} created: {issue['html_url']}"
    except Exception as e:
        logger.error(f"github_create_issue error: {e}")
        return f"Error creating issue: {e}"


async def github_get_pull_request(repo: str, pr_number: int, chat_id: int = 0) -> str:
    """Get details of a pull request."""
    try:
        async with aiohttp.ClientSession() as session:
            url = f"{GITHUB_API}/repos/{repo}/pulls/{pr_number}"
            async with session.get(url, headers=_auth_headers(), timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    return f"GitHub API error: {resp.status}"
                pr = await resp.json()

        lines = [
            f"**PR #{pr['number']}: {pr['title']}**",
            f"State: {pr['state']} | Merged: {pr.get('merged', False)}",
            f"Author: {pr['user']['login']}",
            f"Branch: {pr['head']['ref']} -> {pr['base']['ref']}",
            f"Changed files: {pr.get('changed_files', '?')} | +{pr.get('additions', '?')} -{pr.get('deletions', '?')}",
            f"URL: {pr['html_url']}",
        ]
        if pr.get("body"):
            lines.append(f"\n{pr['body'][:500]}")
        return "\n".join(lines)
    except Exception as e:
        logger.error(f"github_get_pull_request error: {e}")
        return f"Error getting PR: {e}"


async def github_list_notifications(chat_id: int = 0) -> str:
    """List unread GitHub notifications."""
    try:
        async with aiohttp.ClientSession() as session:
            url = f"{GITHUB_API}/notifications?per_page=15"
            async with session.get(url, headers=_auth_headers(), timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    return f"GitHub API error: {resp.status}"
                notifications = await resp.json()

        if not notifications:
            return "No unread notifications."

        lines = []
        for n in notifications[:15]:
            repo = n["repository"]["full_name"]
            reason = n["reason"]
            title = n["subject"]["title"]
            lines.append(f"- [{repo}] {title} ({reason})")
        return "\n".join(lines)
    except Exception as e:
        logger.error(f"github_list_notifications error: {e}")
        return f"Error listing notifications: {e}"


async def github_get_repo_tree(repo: str, path: str = "", branch: str = "", chat_id: int = 0) -> str:
    """List files and directories in a GitHub repository path."""
    try:
        async with aiohttp.ClientSession() as session:
            ref = f"?ref={branch}" if branch else ""
            url = f"{GITHUB_API}/repos/{repo}/contents/{path}{ref}"
            async with session.get(url, headers=_auth_headers(), timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    return f"GitHub API error: {resp.status}"
                contents = await resp.json()

        if isinstance(contents, dict):
            # Single file, not a directory
            return f"- {contents['name']} ({contents['type']}, {contents.get('size', 0)} bytes)"

        lines = []
        dirs = sorted([c for c in contents if c["type"] == "dir"], key=lambda x: x["name"])
        files = sorted([c for c in contents if c["type"] != "dir"], key=lambda x: x["name"])
        for item in dirs:
            lines.append(f"📁 {item['name']}/")
        for item in files:
            size = item.get("size", 0)
            lines.append(f"   {item['name']} ({size} bytes)")
        return f"Contents of {repo}/{path or '(root)'}:\n" + "\n".join(lines)
    except Exception as e:
        logger.error(f"github_get_repo_tree error: {e}")
        return f"Error listing repo contents: {e}"


async def github_get_file_content(repo: str, path: str, branch: str = "", chat_id: int = 0) -> str:
    """Read the content of a file from a GitHub repository."""
    try:
        async with aiohttp.ClientSession() as session:
            ref = f"?ref={branch}" if branch else ""
            url = f"{GITHUB_API}/repos/{repo}/contents/{path}{ref}"
            headers = dict(_auth_headers())
            headers["Accept"] = "application/vnd.github.raw+json"
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    return f"GitHub API error: {resp.status}"
                text = await resp.text()

        # Truncate very large files
        if len(text) > 8000:
            text = text[:8000] + f"\n\n... (truncated, {len(text)} total chars)"
        return f"**{repo}/{path}:**\n```\n{text}\n```"
    except Exception as e:
        logger.error(f"github_get_file_content error: {e}")
        return f"Error reading file: {e}"
