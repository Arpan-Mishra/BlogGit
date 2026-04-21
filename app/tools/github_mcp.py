"""
GitHub tools built on the GitHub REST API via httpx.

These tools are used by the repo_analyzer node to gather information about
a repository. Each tool is exposed as a LangChain StructuredTool so it can
be injected into LangGraph tool nodes.

We use the REST API directly (not an MCP server) because:
- The `@github/mcp-server` npm package does not exist as a published package.
- httpx gives us a simple, dependency-light path with full type safety.
- The GitHub REST API is stable and well-documented.
"""

import base64
import logging
from typing import Any

import httpx
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_GITHUB_API_BASE = "https://api.github.com"
_DEFAULT_TIMEOUT = 15.0


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _get(path: str, token: str, params: dict[str, Any] | None = None) -> Any:
    """Synchronous GET to the GitHub API. Raises httpx.HTTPStatusError on 4xx/5xx."""
    url = f"{_GITHUB_API_BASE}{path}"
    with httpx.Client(timeout=_DEFAULT_TIMEOUT) as client:
        response = client.get(url, headers=_headers(token), params=params)
        response.raise_for_status()
        return response.json()


# ---------------------------------------------------------------------------
# Tool schemas (Pydantic models for StructuredTool)
# ---------------------------------------------------------------------------


class GetReadmeInput(BaseModel):
    owner: str = Field(description="Repository owner (user or org)")
    repo: str = Field(description="Repository name")


class GetFileTreeInput(BaseModel):
    owner: str = Field(description="Repository owner (user or org)")
    repo: str = Field(description="Repository name")
    max_entries: int = Field(
        default=200, description="Maximum number of tree entries to return"
    )


class GetRecentCommitsInput(BaseModel):
    owner: str = Field(description="Repository owner (user or org)")
    repo: str = Field(description="Repository name")
    n: int = Field(default=10, description="Number of recent commits to retrieve")


class GetRepoMetadataInput(BaseModel):
    owner: str = Field(description="Repository owner (user or org)")
    repo: str = Field(description="Repository name")


# ---------------------------------------------------------------------------
# Tool implementation functions
# ---------------------------------------------------------------------------


def get_readme(owner: str, repo: str, *, token: str) -> str:
    """Fetch the README content for a repository.

    Returns the decoded text. If no README exists, returns an empty string.
    """
    try:
        data = _get(f"/repos/{owner}/{repo}/readme", token)
        encoded = data.get("content", "")
        # GitHub returns base64-encoded content with newlines
        return base64.b64decode(encoded.replace("\n", "")).decode("utf-8", errors="replace")
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            logger.warning("No README found for %s/%s", owner, repo)
            return ""
        raise


def get_file_tree(owner: str, repo: str, *, token: str, max_entries: int = 200) -> str:
    """Fetch the flat file tree for the default branch.

    Returns a newline-joined list of paths truncated to *max_entries*.
    """
    # First get the default branch SHA
    repo_data = _get(f"/repos/{owner}/{repo}", token)
    default_branch = repo_data.get("default_branch", "main")

    # Get the tree (recursive)
    tree_data = _get(
        f"/repos/{owner}/{repo}/git/trees/{default_branch}",
        token,
        params={"recursive": "1"},
    )
    entries = tree_data.get("tree", [])
    paths = [e["path"] for e in entries if e.get("type") != "tree"]
    return "\n".join(paths[:max_entries])


def get_recent_commits(owner: str, repo: str, *, token: str, n: int = 10) -> str:
    """Fetch the *n* most recent commits in short log format.

    Returns one commit per line: ``<sha7> <message>``.
    """
    commits = _get(f"/repos/{owner}/{repo}/commits", token, params={"per_page": n})
    lines: list[str] = []
    for c in commits[:n]:
        sha = c.get("sha", "")[:7]
        message = c.get("commit", {}).get("message", "").splitlines()[0]
        lines.append(f"{sha} {message}")
    return "\n".join(lines)


def get_repo_metadata(owner: str, repo: str, *, token: str) -> str:
    """Fetch top-level repository metadata (language, topics, description).

    Returns a compact human-readable summary string.
    """
    data = _get(f"/repos/{owner}/{repo}", token)
    language = data.get("language") or "unknown"
    description = data.get("description") or ""
    topics = data.get("topics") or []
    stars = data.get("stargazers_count", 0)
    return (
        f"Language: {language}\n"
        f"Description: {description}\n"
        f"Topics: {', '.join(topics) if topics else 'none'}\n"
        f"Stars: {stars}"
    )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def build_github_tools(github_token: str) -> list[StructuredTool]:
    """Return a list of StructuredTools pre-bound with *github_token*.

    These tools are ready to be injected into a LangGraph tool node or
    directly into the repo_analyzer node.
    """
    return [
        StructuredTool.from_function(
            func=lambda owner, repo: get_readme(owner, repo, token=github_token),
            name="get_readme",
            description="Fetch the README content of a GitHub repository.",
            args_schema=GetReadmeInput,
        ),
        StructuredTool.from_function(
            func=lambda owner, repo, max_entries=200: get_file_tree(
                owner, repo, token=github_token, max_entries=max_entries
            ),
            name="get_file_tree",
            description=(
                "Fetch the flat file tree of a GitHub repository. "
                "Returns a newline-joined list of file paths."
            ),
            args_schema=GetFileTreeInput,
        ),
        StructuredTool.from_function(
            func=lambda owner, repo, n=10: get_recent_commits(
                owner, repo, token=github_token, n=n
            ),
            name="get_recent_commits",
            description=(
                "Fetch recent commits from a GitHub repository. "
                "Returns one commit per line: '<sha7> <message>'."
            ),
            args_schema=GetRecentCommitsInput,
        ),
        StructuredTool.from_function(
            func=lambda owner, repo: get_repo_metadata(owner, repo, token=github_token),
            name="get_repo_metadata",
            description=(
                "Fetch top-level metadata for a GitHub repository "
                "(language, description, topics, stars)."
            ),
            args_schema=GetRepoMetadataInput,
        ),
    ]
