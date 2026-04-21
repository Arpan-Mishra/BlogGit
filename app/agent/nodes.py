"""
LangGraph node functions for Blog Copilot.

Each node is a pure async function that takes a BlogState dict and returns
a partial state update dict. Nodes never mutate the incoming state.

Factory pattern is used for nodes that need injected dependencies (tools,
LLM instances) so that tests can inject doubles without patching globals.
"""

import logging
import re
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.agent.state import BlogState, DraftVersion, RepoSummary

_PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def parse_github_url(url: str) -> tuple[str, str]:
    """Parse a GitHub repository URL and return (owner, repo).

    Accepts:
        https://github.com/owner/repo
        https://github.com/owner/repo.git
        https://github.com/owner/repo/

    Raises:
        ValueError: if the URL is not a valid GitHub repo URL.
    """
    pattern = r"^https://github\.com/([^/]+)/([^/]+?)(?:\.git)?/?$"
    match = re.match(pattern, url.strip())
    if not match:
        raise ValueError(
            f"Invalid GitHub repository URL: {url!r}. "
            "Expected format: https://github.com/owner/repo"
        )
    owner, repo = match.group(1), match.group(2)
    return owner, repo


def _extract_tool(tools: list[Any], name: str) -> Any | None:
    """Return the first tool whose .name matches *name*, or None."""
    for t in tools:
        if hasattr(t, "name") and t.name == name:
            return t
    return None


# ---------------------------------------------------------------------------
# repo_analyzer node factory
# ---------------------------------------------------------------------------


def make_repo_analyzer_node(
    tools: list[Any],
    llm: Any,
) -> Any:
    """Return an async LangGraph node function for repo analysis.

    Parameters
    ----------
    tools:
        List of StructuredTool (or any object with .name and .ainvoke).
        Expected tools: get_readme, get_file_tree, get_recent_commits,
        get_repo_metadata.
    llm:
        An LLM instance with an async .ainvoke method. In production this
        is a Claude model; in tests it is a mock that returns a RepoSummary.

    Returns
    -------
    An async function ``node(state: BlogState) -> dict`` suitable for use as
    a LangGraph StateGraph node.
    """
    readme_tool = _extract_tool(tools, "get_readme")
    tree_tool = _extract_tool(tools, "get_file_tree")
    commits_tool = _extract_tool(tools, "get_recent_commits")
    metadata_tool = _extract_tool(tools, "get_repo_metadata")

    async def repo_analyzer_node(state: BlogState) -> dict:
        repo_url = state.get("repo_url")
        if not repo_url:
            raise ValueError("repo_url is required in state to run repo_analyzer")

        from app.agent.nodes import parse_github_url

        owner, repo = parse_github_url(repo_url)
        logger.info("Analyzing repo: %s/%s", owner, repo)

        # Gather raw data from GitHub tools (best-effort — skip on error)
        readme = ""
        file_tree = ""
        commits_log = ""
        repo_metadata = ""

        if readme_tool:
            try:
                readme = await readme_tool.ainvoke({"owner": owner, "repo": repo})
            except Exception as exc:
                logger.warning("get_readme failed: %s", exc)

        if tree_tool:
            try:
                file_tree = await tree_tool.ainvoke({"owner": owner, "repo": repo})
            except Exception as exc:
                logger.warning("get_file_tree failed: %s", exc)

        if commits_tool:
            try:
                commits_log = await commits_tool.ainvoke({"owner": owner, "repo": repo})
            except Exception as exc:
                logger.warning("get_recent_commits failed: %s", exc)

        if metadata_tool:
            try:
                repo_metadata = await metadata_tool.ainvoke({"owner": owner, "repo": repo})
            except Exception as exc:
                logger.warning("get_repo_metadata failed: %s", exc)

        # Delegate structured extraction to the LLM
        prompt = _build_analysis_prompt(
            owner=owner,
            repo=repo,
            readme=readme,
            file_tree=file_tree,
            commits_log=commits_log,
            repo_metadata=repo_metadata,
        )
        summary: RepoSummary = await llm.ainvoke(prompt)

        logger.info("RepoSummary produced: language=%s purpose=%r", summary.language, summary.purpose[:60])

        return {
            "repo_summary": summary,
            "phase": "intake",
        }

    return repo_analyzer_node


def _build_analysis_prompt(
    *,
    owner: str,
    repo: str,
    readme: str,
    file_tree: str,
    commits_log: str,
    repo_metadata: str,
) -> str:
    """Construct the prompt sent to the LLM for structured repo analysis."""
    readme_excerpt = readme if readme else "(no README found)"
    tree_excerpt = file_tree[:3000] if file_tree else "(no file tree available)"
    commits_excerpt = commits_log[:2000] if commits_log else "(no commits available)"

    return f"""You are analyzing the GitHub repository {owner}/{repo} to produce a structured summary for a blog post.

## Repository Metadata
{repo_metadata or "(not available)"}

## README
{readme_excerpt}

## File Tree (first 3000 chars)
{tree_excerpt}

## Recent Commits
{commits_excerpt}

Based on this information, produce a RepoSummary with:
- language: the primary programming language
- modules: the top-level modules or packages (as a tuple of strings)
- purpose: a concise 1-2 sentence description of what the project does
- notable_commits: the most interesting commits from the log (as a tuple of strings)
- readme_excerpt: the first 500 chars of the README

Return ONLY a RepoSummary frozen dataclass object. Do not include any explanation."""


# ---------------------------------------------------------------------------
# Intake questions
# ---------------------------------------------------------------------------

INTAKE_QUESTIONS: list[tuple[str, str]] = [
    ("audience", "Who is the target audience for this blog post? (e.g., senior engineers, data scientists, junior developers, general tech readers)"),
    ("tone", "What tone should the post have? (e.g., technical deep-dive, conversational, storytelling, tutorial-style)"),
    ("emphasis", "What aspects of the project should be emphasized? (e.g., architecture decisions, performance gains, problem-solving process, specific algorithms)"),
    ("avoid", "Is there anything that should NOT be mentioned? (e.g., internal client names, unfinished features, certain implementation details)"),
    ("extra_instructions", "Any other context or instructions for writing the post?"),
]


# ---------------------------------------------------------------------------
# intake node factory
# ---------------------------------------------------------------------------


def make_intake_node() -> Any:
    """Return an async LangGraph node function for the intake phase.

    The node is deterministic — it asks exactly one question per turn,
    in fixed order, using INTAKE_QUESTIONS. No LLM is involved.

    State flow:
      - Detects which question was last asked (by scanning AIMessages).
      - Stores the last HumanMessage as the answer to that question.
      - Asks the next unanswered question, or transitions phase to "draft"
        when all five answers have been collected.
    """

    async def intake_node(state: BlogState) -> dict:
        messages: list = list(state.get("messages", []))
        intake_answers: dict[str, str] = dict(state.get("intake_answers", {}))

        # Detect the index of the last question asked (if any).
        last_asked_index: int = -1
        for i, (_, q_text) in enumerate(INTAKE_QUESTIONS):
            for m in messages:
                if isinstance(m, AIMessage) and q_text in m.content:
                    last_asked_index = i
                    break

        # If a question was asked, store the last HumanMessage as its answer.
        if last_asked_index >= 0:
            key, _ = INTAKE_QUESTIONS[last_asked_index]
            # Find the last HumanMessage after the AIMessage that asked the question
            human_answers = [m for m in messages if isinstance(m, HumanMessage)]
            if human_answers:
                intake_answers[key] = human_answers[-1].content

        # Determine the next question to ask.
        next_index = last_asked_index + 1

        if next_index >= len(INTAKE_QUESTIONS):
            # All questions answered — transition to drafting
            logger.info("All intake questions answered; transitioning to draft phase")
            return {
                "intake_answers": intake_answers,
                "messages": messages,
                "phase": "draft",
            }

        _, next_q_text = INTAKE_QUESTIONS[next_index]
        logger.info("Intake: asking question %d/%d", next_index + 1, len(INTAKE_QUESTIONS))

        new_messages = messages + [AIMessage(content=next_q_text)]
        return {
            "intake_answers": intake_answers,
            "messages": new_messages,
            "phase": "intake",
        }

    return intake_node


# ---------------------------------------------------------------------------
# drafting node factory
# ---------------------------------------------------------------------------

_MAX_TOOL_ITERATIONS = 5


def make_drafting_node(llm: Any, search_tool: Any | None = None) -> Any:
    """Return an async LangGraph node function for blog post drafting.

    Parameters
    ----------
    llm:
        An LLM instance with an async .ainvoke method and a .bind_tools method.
        In production this is a Claude model; in tests it is a mock.
    search_tool:
        Optional web search tool (e.g. TavilySearchResults). When provided the
        LLM is bound to it and may call it to look up articles or context for
        topics mentioned in the repository or requested via intake answers.
        The tool-calling loop runs at most ``_MAX_TOOL_ITERATIONS`` times.

    Returns
    -------
    An async function ``node(state: BlogState) -> dict`` suitable for use as
    a LangGraph StateGraph node.
    """

    async def drafting_node(state: BlogState) -> dict:
        repo_summary: RepoSummary | None = state.get("repo_summary")
        if repo_summary is None:
            raise ValueError("repo_summary is required in state to run drafting node")

        intake_answers: dict[str, str] = state.get("intake_answers", {})
        revision_history: list = list(state.get("revision_history", []))
        messages: list = list(state.get("messages", []))

        system_prompt = (_PROMPTS_DIR / "drafting.md").read_text()

        prompt = _build_drafting_prompt(
            system_prompt=system_prompt,
            repo_summary=repo_summary,
            intake_answers=intake_answers,
        )

        logger.info("Drafting blog post for repo: %s", state.get("repo_url", "unknown"))

        if search_tool is not None:
            draft_text = await _draft_with_search(llm=llm, search_tool=search_tool, prompt=prompt)
        else:
            response = await llm.ainvoke(prompt)
            draft_text = response.content if hasattr(response, "content") else str(response)

        version = len(revision_history) + 1
        draft_version = DraftVersion(version=version, content=draft_text)

        logger.info("Draft v%d produced (%d chars)", version, len(draft_text))

        return {
            "current_draft": draft_text,
            "revision_history": revision_history + [draft_version],
            "messages": messages + [AIMessage(content=draft_text)],
            "phase": "revise",
        }

    return drafting_node


async def _draft_with_search(*, llm: Any, search_tool: Any, prompt: str) -> str:
    """Run the tool-calling loop: let the LLM call the search tool up to
    ``_MAX_TOOL_ITERATIONS`` times, then return its final text response.
    """
    llm_with_tools = llm.bind_tools([search_tool])
    messages: list = [HumanMessage(content=prompt)]
    response: Any = None

    for _ in range(_MAX_TOOL_ITERATIONS):
        response = await llm_with_tools.ainvoke(messages)
        messages.append(response)

        tool_calls = getattr(response, "tool_calls", None) or []
        if not tool_calls:
            break

        for tool_call in tool_calls:
            logger.info("Drafting: search query=%r", tool_call.get("args", {}).get("query", ""))
            try:
                raw = await search_tool.ainvoke(tool_call["args"])
                # TavilySearch returns a dict with a "results" list; flatten to text
                if isinstance(raw, dict) and "results" in raw:
                    articles = raw["results"]
                    content = "\n\n".join(
                        f"Title: {a.get('title', '')}\nURL: {a.get('url', '')}\n{a.get('content', '')}"
                        for a in articles
                    )
                else:
                    content = str(raw)
            except Exception as exc:
                logger.warning("Search tool error: %s", exc)
                content = f"(search failed: {exc})"
            messages.append(
                ToolMessage(content=content, tool_call_id=tool_call["id"])
            )

    if response is None:
        return ""
    return response.content if hasattr(response, "content") else str(response)


def _build_drafting_prompt(
    *,
    system_prompt: str,
    repo_summary: RepoSummary,
    intake_answers: dict[str, str],
) -> str:
    """Construct the prompt sent to the LLM for blog post drafting."""
    answers_block = "\n".join(
        f"- **{key.replace('_', ' ').title()}:** {value}"
        for key, value in intake_answers.items()
    )

    return f"""{system_prompt}

## Repository Summary

- **Language:** {repo_summary.language}
- **Purpose:** {repo_summary.purpose}
- **Key Modules:** {', '.join(repo_summary.modules)}
- **Notable Commits:**
{chr(10).join(f"  - {c}" for c in repo_summary.notable_commits)}

## README Excerpt

{repo_summary.readme_excerpt or "(none)"}

## Intake Answers

{answers_block or "(no intake answers provided)"}

Now write the blog post following the drafting guidelines above."""


# ---------------------------------------------------------------------------
# revision node factory
# ---------------------------------------------------------------------------


def make_revision_node(llm: Any) -> Any:
    """Return an async LangGraph node function for blog post revision.

    Parameters
    ----------
    llm:
        An LLM instance with an async .ainvoke method. In production this
        is a Claude model; in tests it is a mock.

    Returns
    -------
    An async function ``node(state: BlogState) -> dict`` suitable for use as
    a LangGraph StateGraph node.
    """

    async def revision_node(state: BlogState) -> dict:
        current_draft = state.get("current_draft")
        if not current_draft:
            raise ValueError("current_draft is required in state to run revision node")

        messages: list = list(state.get("messages", []))
        revision_history: list = list(state.get("revision_history", []))

        # The last HumanMessage is the user's revision feedback.
        human_messages = [m for m in messages if isinstance(m, HumanMessage)]
        user_feedback = human_messages[-1].content if human_messages else ""

        system_prompt = (_PROMPTS_DIR / "revision.md").read_text()
        prompt = _build_revision_prompt(
            system_prompt=system_prompt,
            current_draft=current_draft,
            user_feedback=user_feedback,
        )

        logger.info("Revision requested: feedback=%r", user_feedback[:80])

        response = await llm.ainvoke(prompt)
        new_draft = response.content if hasattr(response, "content") else str(response)

        version = len(revision_history) + 1
        draft_version = DraftVersion(version=version, content=new_draft, user_feedback=user_feedback)

        logger.info("Revision v%d produced (%d chars)", version, len(new_draft))

        return {
            "current_draft": new_draft,
            "revision_history": revision_history + [draft_version],
            "messages": messages + [AIMessage(content=new_draft)],
            "phase": "revise",
        }

    return revision_node


def _build_revision_prompt(
    *,
    system_prompt: str,
    current_draft: str,
    user_feedback: str,
) -> str:
    """Construct the prompt sent to the LLM for blog post revision."""
    return f"""{system_prompt}

## Current Draft

{current_draft}

## Author Feedback

{user_feedback}

Now produce the revised blog post."""
