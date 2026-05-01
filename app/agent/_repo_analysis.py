"""
Three-phase deterministic repo analysis pipeline (Sprint 10).

This module keeps the `repo_analyzer` node body thin. Each phase is a pure
async function that can be tested in isolation.

Phases
------
1. phase1_fetch   — parallel baseline fetch (README, file tree, commits, metadata)
2. phase2_explore — LLM-guided selection of specific files and search queries to run
3. phase3_synthesize — LLM synthesis into a rich RepoSummary
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from app.agent.state import RepoSummary

logger = logging.getLogger(__name__)

_PROMPTS_PATH = Path(__file__).parent.parent.parent / "prompts" / "repo_analyzer.md"

# Hard caps enforced in phase2 to stay within rate-limit and latency budgets
_MAX_FILES_TO_FETCH = 5
_MAX_SEARCH_QUERIES = 3


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BaselineData:
    """Raw data fetched in Phase 1 from the GitHub API."""

    readme: str
    file_tree: str
    commits_log: str
    repo_metadata: str


@dataclass(frozen=True)
class ExplorationData:
    """File contents and search results gathered in Phase 2."""

    file_contents: dict[str, str] = field(default_factory=dict)
    search_results: dict[str, str] = field(default_factory=dict)


class ExplorationPlan(BaseModel):
    """Pydantic model for parsing the Phase 2 LLM output."""

    files_to_fetch: list[str] = Field(default_factory=list)
    search_queries: list[str] = Field(default_factory=list)
    reasoning: str = Field(default="")


# ---------------------------------------------------------------------------
# Prompt loading
# ---------------------------------------------------------------------------


def _load_prompts() -> tuple[str, str]:
    """Load exploration and synthesis prompts from prompts/repo_analyzer.md.

    Splits the file on ``## Section 2:`` to extract the two sections.
    Returns (exploration_prompt, synthesis_prompt).
    """
    raw = _PROMPTS_PATH.read_text(encoding="utf-8")
    parts = raw.split("## Section 2:", maxsplit=1)
    exploration = parts[0].strip()
    synthesis = ("## Section 2:" + parts[1]).strip() if len(parts) > 1 else raw.strip()
    return exploration, synthesis


# ---------------------------------------------------------------------------
# Safe tool invocation helper
# ---------------------------------------------------------------------------


async def _safe_invoke(tool: Any, params: dict) -> str:
    """Call tool.ainvoke catching all exceptions; returns empty string on failure."""
    try:
        result = await tool.ainvoke(params)
        return result if isinstance(result, str) else str(result)
    except Exception as exc:
        logger.warning("Tool %s failed: %s", getattr(tool, "name", "?"), exc)
        return ""


# ---------------------------------------------------------------------------
# Phase 1 — Parallel baseline fetch
# ---------------------------------------------------------------------------


async def phase1_fetch(
    owner: str,
    repo: str,
    tools: list[Any],
) -> BaselineData:
    """Fetch README, full file tree, recent commits, and repo metadata in parallel.

    Uses max_entries=2000 (was 200) and n=20 commits (was 10) to capture more
    context. All tool calls are best-effort — failures return empty strings.
    """
    tool_map: dict[str, Any] = {t.name: t for t in tools if hasattr(t, "name")}

    async def _empty() -> str:
        return ""

    readme_task = (
        _safe_invoke(tool_map["get_readme"], {"owner": owner, "repo": repo})
        if "get_readme" in tool_map
        else _empty()
    )
    tree_task = (
        _safe_invoke(
            tool_map["get_file_tree"],
            {"owner": owner, "repo": repo, "max_entries": 2000},
        )
        if "get_file_tree" in tool_map
        else _empty()
    )
    commits_task = (
        _safe_invoke(tool_map["get_recent_commits"], {"owner": owner, "repo": repo, "n": 20})
        if "get_recent_commits" in tool_map
        else _empty()
    )
    metadata_task = (
        _safe_invoke(tool_map["get_repo_metadata"], {"owner": owner, "repo": repo})
        if "get_repo_metadata" in tool_map
        else _empty()
    )

    readme, file_tree, commits_log, repo_metadata = await asyncio.gather(
        readme_task, tree_task, commits_task, metadata_task
    )

    logger.info(
        "phase1_fetch complete: readme=%d chars, tree=%d chars, commits=%d chars",
        len(readme),
        len(file_tree),
        len(commits_log),
    )
    return BaselineData(
        readme=readme,
        file_tree=file_tree,
        commits_log=commits_log,
        repo_metadata=repo_metadata,
    )


# ---------------------------------------------------------------------------
# Phase 2 — Intent-driven exploration
# ---------------------------------------------------------------------------


async def phase2_explore(
    owner: str,
    repo: str,
    tools: list[Any],
    baseline: BaselineData,
    user_intent: str,
    llm: Any,
) -> ExplorationData:
    """Ask the LLM which files to read and patterns to search, then execute.

    The LLM receives the file tree and user intent and returns an
    ExplorationPlan. We enforce hard caps (5 files, 3 queries) regardless of
    what the LLM returns.
    """
    exploration_prompt, _ = _load_prompts()

    filled = exploration_prompt.format(
        user_intent=user_intent or "(not specified)",
        file_tree=baseline.file_tree[:5000] if baseline.file_tree else "(no file tree)",
    )

    raw_response = await llm.ainvoke(filled)
    raw_text: str = (
        raw_response.content
        if hasattr(raw_response, "content")
        else str(raw_response)
    )

    # Strip markdown fences if model wraps the JSON anyway
    if raw_text.strip().startswith("```"):
        raw_text = raw_text.strip().split("\n", 1)[-1]
        raw_text = raw_text.rsplit("```", 1)[0].strip()

    try:
        plan_data = json.loads(raw_text)
        plan = ExplorationPlan(**plan_data)
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        logger.warning("Phase 2 LLM returned invalid JSON: %s — using empty plan", exc)
        plan = ExplorationPlan()

    # Enforce hard caps
    files_to_fetch = plan.files_to_fetch[:_MAX_FILES_TO_FETCH]
    search_queries = plan.search_queries[:_MAX_SEARCH_QUERIES]
    logger.info(
        "Phase 2 plan: files=%s queries=%s reasoning=%r",
        files_to_fetch,
        search_queries,
        plan.reasoning[:80],
    )

    tool_map: dict[str, Any] = {t.name: t for t in tools if hasattr(t, "name")}
    file_tool = tool_map.get("get_file_contents")
    search_tool_obj = tool_map.get("search_code")

    file_contents: dict[str, str] = {}
    for path in files_to_fetch:
        result = await _safe_invoke(
            file_tool, {"owner": owner, "repo": repo, "path": path}
        ) if file_tool else ""
        file_contents[path] = result

    search_results: dict[str, str] = {}
    for query in search_queries:
        result = await _safe_invoke(
            search_tool_obj, {"owner": owner, "repo": repo, "query": query}
        ) if search_tool_obj else ""
        search_results[query] = result

    return ExplorationData(file_contents=file_contents, search_results=search_results)


# ---------------------------------------------------------------------------
# Phase 3 — Rich synthesis
# ---------------------------------------------------------------------------


def _format_file_contents(file_contents: dict[str, str]) -> str:
    if not file_contents:
        return "(none fetched)"
    parts = []
    for path, content in file_contents.items():
        parts.append(f"### {path}\n{content}")
    return "\n\n".join(parts)


def _format_search_results(search_results: dict[str, str]) -> str:
    if not search_results:
        return "(none)"
    parts = []
    for query, result in search_results.items():
        parts.append(f"Query: {query!r}\n{result}")
    return "\n\n".join(parts)


async def phase3_synthesize(
    owner: str,
    repo: str,
    baseline: BaselineData,
    exploration: ExplorationData,
    user_intent: str,
    llm: Any,
) -> RepoSummary:
    """Call the synthesis LLM to produce a rich RepoSummary from all gathered data."""
    _, synthesis_prompt = _load_prompts()

    filled = synthesis_prompt.format(
        repo_metadata=baseline.repo_metadata or "(not available)",
        readme=baseline.readme[:8000] if baseline.readme else "(no README found)",
        file_tree=baseline.file_tree[:5000] if baseline.file_tree else "(no file tree available)",
        commits_log=baseline.commits_log[:2000] if baseline.commits_log else "(no commits available)",
        file_contents=_format_file_contents(exploration.file_contents),
        search_results=_format_search_results(exploration.search_results),
        user_intent=user_intent or "(not specified)",
    )

    raw_response = await llm.ainvoke(filled)
    raw_text: str = (
        raw_response.content
        if hasattr(raw_response, "content")
        else str(raw_response)
    )

    # Strip markdown fences
    if raw_text.strip().startswith("```"):
        raw_text = raw_text.strip().split("\n", 1)[-1]
        raw_text = raw_text.rsplit("```", 1)[0].strip()

    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        logger.warning("Phase 3 LLM returned invalid JSON: %s — using fallback RepoSummary", exc)
        data = {}

    summary = RepoSummary(
        language=data.get("language", "unknown"),
        modules=tuple(data.get("modules", [])),
        purpose=data.get(
            "purpose",
            "Repository purpose could not be determined from available data.",
        ),
        notable_commits=tuple(data.get("notable_commits", [])),
        readme_excerpt=data.get("readme_excerpt", baseline.readme[:500]),
        key_files=tuple(data.get("key_files", [])),
        code_insights=tuple(data.get("code_insights", [])),
        tech_stack=tuple(data.get("tech_stack", [])),
        architecture_notes=data.get("architecture_notes", ""),
        user_intent=data.get("user_intent", user_intent),
    )

    logger.info(
        "RepoSummary produced: language=%s purpose=%r key_files=%d",
        summary.language,
        summary.purpose[:60],
        len(summary.key_files),
    )
    return summary
