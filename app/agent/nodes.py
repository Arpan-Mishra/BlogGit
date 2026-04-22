"""
LangGraph node functions for Blog Copilot.

Each node is a pure async function that takes a BlogState dict and returns
a partial state update dict. Nodes never mutate the incoming state.

Factory pattern is used for nodes that need injected dependencies (tools,
LLM instances) so that tests can inject doubles without patching globals.
"""

import json
import logging
import re
from pathlib import Path
from typing import Any, Awaitable, Callable

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


_CITATION_RE = re.compile(
    r"(?:add|include|cite|reference|citation)\b.*?(https?://\S+)", re.IGNORECASE
)

# ---------------------------------------------------------------------------
# Medium formatting helpers
# ---------------------------------------------------------------------------

_MERMAID_FENCE_RE = re.compile(r"```mermaid\n(.*?)\n```", re.DOTALL)
_H2_RE = re.compile(r"^## (.+)$", re.MULTILINE)
_H3_RE = re.compile(r"^### (.+)$", re.MULTILINE)


def _mermaid_to_blockquote(match: re.Match) -> str:  # type: ignore[type-arg]
    """Replace a mermaid fence with a plain italic blockquote.

    Extracts node labels from the diagram code to form a human-readable
    description.  Falls back to a generic description when no labels are found.
    """
    diagram_code = match.group(1)
    node_labels = re.findall(r"\[([^\]]+)\]", diagram_code)
    if node_labels:
        description = " → ".join(node_labels[:6])
        return f"> *Diagram: {description}*"
    return "> *Architecture diagram showing system components and their relationships.*"


def _adapt_content_for_medium(content: str) -> str:
    """Apply deterministic Medium formatting fixes to markdown content.

    Medium's paste-from-clipboard import does not render:
      - Mermaid fenced code blocks (shows raw syntax)
      - ## / ### heading markers (shows literal '#' characters)

    This function converts both to Medium-compatible equivalents:
      - Mermaid blocks → italic blockquotes describing the diagram
      - ## Heading → Heading  (no '#' prefix; blank lines preserved by caller)
      - ### Sub-heading → Sub-heading
      - # Title (H1) is left untouched — Medium uses it as the story title.
    """
    content = _MERMAID_FENCE_RE.sub(_mermaid_to_blockquote, content)
    content = _H2_RE.sub(r"\1", content)
    content = _H3_RE.sub(r"\1", content)
    return content


def _extract_citation_url(text: str) -> str | None:
    """Return a URL from a user message that expresses intent to cite a source.

    Matches patterns like:
      "add citation: https://example.com"
      "please include https://arxiv.org/abs/... as a reference"
      "cite this: https://..."

    Returns the URL stripped of trailing punctuation, or None if no match.
    """
    m = _CITATION_RE.search(text)
    return m.group(1).rstrip(".,)") if m else None


# ---------------------------------------------------------------------------
# repo_analyzer node factory
# ---------------------------------------------------------------------------


def make_repo_analyzer_node(
    tools: list[Any],
    llm: Any,
) -> Callable[[BlogState], Awaitable[dict[str, Any]]]:
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


def make_intake_node() -> Callable[[BlogState], Awaitable[dict[str, Any]]]:
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
        user_citations: tuple[str, ...] = state.get("user_citations", ())

        # Check if the latest human message is a citation request — intercept
        # before normal intake processing so the question is re-asked afterward.
        human_messages = [m for m in messages if isinstance(m, HumanMessage)]
        if human_messages:
            latest_human = human_messages[-1].content
            citation_url = _extract_citation_url(latest_human)
            if citation_url:
                logger.info("Intake: citation URL intercepted: %s", citation_url)
                user_citations = user_citations + (citation_url,)

                # Find the current unanswered question to re-ask it.
                last_asked_index = -1
                for i, (_, q_text) in enumerate(INTAKE_QUESTIONS):
                    for m in messages:
                        if isinstance(m, AIMessage) and q_text in m.content:
                            last_asked_index = i
                            break

                current_q_text = (
                    INTAKE_QUESTIONS[last_asked_index][1]
                    if last_asked_index >= 0
                    else INTAKE_QUESTIONS[0][1]
                )
                confirm_msg = (
                    f"Got it — I'll include {citation_url} in the References section.\n\n"
                    f"{current_q_text}"
                )
                return {
                    "user_citations": user_citations,
                    "messages": messages + [AIMessage(content=confirm_msg)],
                    "phase": "intake",
                }

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
            if human_messages:
                intake_answers[key] = human_messages[-1].content

        # Determine the next question to ask.
        next_index = last_asked_index + 1

        if next_index >= len(INTAKE_QUESTIONS):
            # All questions answered — transition to outline planning
            logger.info("All intake questions answered; transitioning to outline phase")
            return {
                "intake_answers": intake_answers,
                "user_citations": user_citations,
                "messages": messages,
                "phase": "outline",
            }

        _, next_q_text = INTAKE_QUESTIONS[next_index]
        logger.info("Intake: asking question %d/%d", next_index + 1, len(INTAKE_QUESTIONS))

        new_messages = messages + [AIMessage(content=next_q_text)]
        return {
            "intake_answers": intake_answers,
            "user_citations": user_citations,
            "messages": new_messages,
            "phase": "intake",
        }

    return intake_node


# ---------------------------------------------------------------------------
# Outline node factory
# ---------------------------------------------------------------------------

# Keywords that signal the user has approved the outline.
_APPROVAL_PATTERNS: list[str] = [
    r"\byes\b",
    r"\byep\b",
    r"\byeah\b",
    r"\bsure\b",
    r"\bok\b",
    r"\bokay\b",
    r"\blooks good\b",
    r"\blooks great\b",
    r"\bgreat\b",
    r"\bgo ahead\b",
    r"\bapproved?\b",
    r"\bstart\b",
    r"\bbegin\b",
    r"\bwrite it\b",
    r"\bproceed\b",
    r"\bgo for it\b",
    r"\bthis is good\b",
    r"\bthis looks good\b",
    r"\bfine\b",
    r"\bperfect\b",
    r"\bsounds? good\b",
    r"\blgtm\b",
]


def _is_approval(text: str) -> bool:
    """Return True if the text is a short approval of the proposed outline."""
    lower = text.lower().strip()
    # Short messages that are purely affirmative — not multi-sentence feedback.
    if len(lower) > 120:
        return False
    return any(re.search(p, lower) for p in _APPROVAL_PATTERNS)


def make_outline_node(llm: Any) -> Callable[[BlogState], Awaitable[dict[str, Any]]]:
    """Return an async LangGraph node function for outline planning.

    Behaviour
    ---------
    - First invocation (no outline_plan in state): generates a proposed section
      outline from the repo summary and intake answers, stores it in state, and
      returns to END so the user can review it.
    - Subsequent invocations: inspects the last HumanMessage.
      - Approval detected  → transitions phase to "draft" (graph continues to
        the drafting node via route_after_outline).
      - Feedback detected  → revises the outline, stores the update, returns to
        END so the user can review the revised outline.
    """

    async def outline_node(state: BlogState) -> dict:
        messages: list = list(state.get("messages", []))
        outline_plan: str | None = state.get("outline_plan")
        repo_summary = state.get("repo_summary")
        intake_answers: dict[str, str] = state.get("intake_answers", {})
        user_citations: tuple[str, ...] = state.get("user_citations", ())

        human_messages = [m for m in messages if isinstance(m, HumanMessage)]

        if outline_plan is not None:
            # We already have an outline — check if the user approved or gave feedback.
            user_response = human_messages[-1].content if human_messages else ""

            # Check for citation intercept before approval/revision logic.
            citation_url = _extract_citation_url(user_response)
            if citation_url:
                logger.info("Outline: citation URL intercepted: %s", citation_url)
                user_citations = user_citations + (citation_url,)
                confirm_msg = (
                    f"Got it — I'll include {citation_url} in the References section.\n\n"
                    "Does the outline look good, or would you like any changes?"
                )
                return {
                    "user_citations": user_citations,
                    "messages": messages + [AIMessage(content=confirm_msg)],
                    "phase": "outline",
                }

            if _is_approval(user_response):
                logger.info("Outline approved; transitioning to draft phase")
                return {"phase": "draft", "user_citations": user_citations}

            # User gave feedback — revise the outline.
            logger.info("Outline feedback received; revising outline")
            system_prompt = (_PROMPTS_DIR / "outline.md").read_text()
            revision_prompt = _build_outline_revision_prompt(
                system_prompt=system_prompt,
                current_outline=outline_plan,
                user_feedback=user_response,
            )
            response = await llm.ainvoke(revision_prompt)
            revised_outline = response.content if hasattr(response, "content") else str(response)

            logger.info("Revised outline produced (%d chars)", len(revised_outline))
            return {
                "outline_plan": revised_outline,
                "user_citations": user_citations,
                "messages": messages + [AIMessage(content=revised_outline)],
                "phase": "outline",
            }

        # First time in outline phase — generate the outline.
        logger.info("Generating outline for repo: %s", state.get("repo_url", "unknown"))
        system_prompt = (_PROMPTS_DIR / "outline.md").read_text()
        generation_prompt = _build_outline_prompt(
            system_prompt=system_prompt,
            repo_summary=repo_summary,
            intake_answers=intake_answers,
        )
        response = await llm.ainvoke(generation_prompt)
        outline = response.content if hasattr(response, "content") else str(response)

        logger.info("Outline produced (%d chars)", len(outline))
        return {
            "outline_plan": outline,
            "user_citations": user_citations,
            "messages": messages + [AIMessage(content=outline)],
            "phase": "outline",
        }

    return outline_node


def _build_outline_prompt(
    *,
    system_prompt: str,
    repo_summary: Any,
    intake_answers: dict[str, str],
) -> str:
    """Construct the prompt for generating an initial blog post outline."""
    answers_block = "\n".join(
        f"- **{key.replace('_', ' ').title()}:** {value}"
        for key, value in intake_answers.items()
    )
    modules = ", ".join(repo_summary.modules) if repo_summary and repo_summary.modules else "(unknown)"
    purpose = repo_summary.purpose if repo_summary else "(unknown)"
    language = repo_summary.language if repo_summary else "(unknown)"
    commits = "\n".join(f"  - {c}" for c in repo_summary.notable_commits) if repo_summary else ""
    readme = repo_summary.readme_excerpt if repo_summary else ""

    return f"""{system_prompt}

## Repository Summary

- **Language:** {language}
- **Purpose:** {purpose}
- **Key Modules:** {modules}
- **Notable Commits:**
{commits or "  (none available)"}

## README Excerpt

{readme or "(none)"}

## Intake Answers

{answers_block or "(no intake answers provided)"}

Now propose the blog post outline."""


def _build_outline_revision_prompt(
    *,
    system_prompt: str,
    current_outline: str,
    user_feedback: str,
) -> str:
    """Construct the prompt for revising an existing outline based on feedback."""
    return f"""{system_prompt}

## Current Outline

{current_outline}

## Author Feedback

{user_feedback}

Revise the outline according to the feedback and re-present it in the same format."""


# ---------------------------------------------------------------------------
# drafting node factory
# ---------------------------------------------------------------------------

_MAX_TOOL_ITERATIONS = 5


def make_drafting_node(
    llm: Any, search_tool: Any | None = None
) -> Callable[[BlogState], Awaitable[dict[str, Any]]]:
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
        outline_plan: str | None = state.get("outline_plan")
        user_citations: tuple[str, ...] = state.get("user_citations", ())
        revision_history: list = list(state.get("revision_history", []))
        messages: list = list(state.get("messages", []))

        system_prompt = (_PROMPTS_DIR / "drafting.md").read_text()

        prompt = _build_drafting_prompt(
            system_prompt=system_prompt,
            repo_summary=repo_summary,
            intake_answers=intake_answers,
            outline_plan=outline_plan,
            user_citations=user_citations,
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
    outline_plan: str | None = None,
    user_citations: tuple[str, ...] = (),
) -> str:
    """Construct the prompt sent to the LLM for blog post drafting."""
    answers_block = "\n".join(
        f"- **{key.replace('_', ' ').title()}:** {value}"
        for key, value in intake_answers.items()
    )

    outline_section = (
        f"\n## Approved Outline\n\nFollow this section structure exactly:\n\n{outline_plan}\n"
        if outline_plan
        else ""
    )

    citations_section = (
        "\n## User-Provided Citations\n\nInclude these URLs in the ## References section:\n"
        + "\n".join(f"- {url}" for url in user_citations)
        + "\n"
        if user_citations
        else ""
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
{outline_section}{citations_section}
Now write the blog post following the drafting guidelines above."""


# ---------------------------------------------------------------------------
# revision node factory
# ---------------------------------------------------------------------------


def make_revision_node(llm: Any) -> Callable[[BlogState], Awaitable[dict[str, Any]]]:
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
        user_citations: tuple[str, ...] = state.get("user_citations", ())

        # The last HumanMessage is the user's revision feedback.
        human_messages = [m for m in messages if isinstance(m, HumanMessage)]
        user_feedback = human_messages[-1].content if human_messages else ""

        # Intercept citation URLs embedded in revision feedback.
        citation_url = _extract_citation_url(user_feedback)
        if citation_url:
            logger.info("Revision: citation URL intercepted: %s", citation_url)
            user_citations = user_citations + (citation_url,)
            user_feedback = (
                f"{user_feedback}\n\nAlso add this URL to the ## References section: {citation_url}"
            )

        system_prompt = (_PROMPTS_DIR / "revision.md").read_text()
        prompt = _build_revision_prompt(
            system_prompt=system_prompt,
            current_draft=current_draft,
            user_feedback=user_feedback,
            user_citations=user_citations,
        )

        logger.info("Revision requested: feedback=%r", user_feedback[:80])

        response = await llm.ainvoke(prompt)
        new_draft = response.content if hasattr(response, "content") else str(response)

        version = len(revision_history) + 1
        draft_version = DraftVersion(version=version, content=new_draft, user_feedback=user_feedback)

        logger.info("Revision v%d produced (%d chars)", version, len(new_draft))

        return {
            "current_draft": new_draft,
            "user_citations": user_citations,
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
    user_citations: tuple[str, ...] = (),
) -> str:
    """Construct the prompt sent to the LLM for blog post revision."""
    citations_section = (
        "\n## User-Provided Citations\n\nEnsure these URLs appear in the ## References section:\n"
        + "\n".join(f"- {url}" for url in user_citations)
        + "\n"
        if user_citations
        else ""
    )

    return f"""{system_prompt}

## Current Draft

{current_draft}

## Author Feedback

{user_feedback}
{citations_section}
Now produce the revised blog post."""


# ---------------------------------------------------------------------------
# notion_publisher node factory
# ---------------------------------------------------------------------------


def make_notion_publisher_node(
    *, token: str, parent_page_id: str
) -> Callable[[BlogState], Awaitable[dict[str, Any]]]:
    """Return an async LangGraph node function for publishing to Notion.

    Parameters
    ----------
    token:
        Notion integration token or OAuth access token.
    parent_page_id:
        UUID of the Notion parent page (with or without dashes).

    Returns
    -------
    An async function ``node(state: BlogState) -> dict`` suitable for use as
    a LangGraph StateGraph node.
    """
    from app.tools.notion_mcp import create_notion_page, extract_title_from_markdown

    async def notion_publisher_node(state: BlogState) -> dict:
        current_draft = state.get("current_draft")
        if not current_draft:
            raise ValueError("current_draft is required in state to run notion_publisher node")

        title = extract_title_from_markdown(current_draft)
        logger.info("Publishing to Notion: title=%r", title)

        page_url = await create_notion_page(
            token=token,
            parent_page_id=parent_page_id,
            title=title,
            content=current_draft,
        )

        # Extract just the page ID from the URL for storage.
        # Notion URLs look like https://notion.so/<id_without_dashes>
        page_id = page_url.rstrip("/").rsplit("/", 1)[-1].split("?")[0]

        logger.info("Notion page published: %s -> %s", title, page_url)

        messages: list = list(state.get("messages", []))
        confirm = (
            f"Your blog post has been published to Notion.\n\n"
            f"**Title:** {title}\n"
            f"**URL:** {page_url}"
        )
        return {
            "notion_page_id": page_id,
            "notion_title": title,
            "messages": messages + [AIMessage(content=confirm)],
            "phase": "notion",
        }

    return notion_publisher_node


# ---------------------------------------------------------------------------
# medium_publisher node factory
# ---------------------------------------------------------------------------


def make_medium_publisher_node(
    llm: Any,
) -> Callable[[BlogState], Awaitable[dict[str, Any]]]:
    """Return an async LangGraph node function for adapting content for Medium.

    The node calls the LLM with ``prompts/medium.md`` to produce a
    Medium-optimised title, subtitle, tags list, and full content.  It stores
    the result in ``medium_markdown`` in state; actual posting to Medium is
    handled by the ``/publish/medium`` API endpoint.

    Parameters
    ----------
    llm:
        An LLM instance with an async ``.ainvoke`` method.

    Returns
    -------
    An async function ``node(state: BlogState) -> dict``.
    """

    async def medium_publisher_node(state: BlogState) -> dict[str, Any]:
        current_draft = state.get("current_draft")
        if not current_draft:
            raise ValueError("current_draft is required in state to run medium_publisher node")

        system_prompt = (_PROMPTS_DIR / "medium.md").read_text()
        prompt = f"{system_prompt}\n\n## Blog Post\n\n{current_draft}\n\nAdapt the post now."

        logger.info("Adapting draft for Medium (%d chars)", len(current_draft))
        response = await llm.ainvoke(prompt)
        raw = response.content if hasattr(response, "content") else str(response)

        # Strip markdown fences if the model wraps the JSON.
        stripped = raw.strip()
        if stripped.startswith("```"):
            stripped = stripped.split("\n", 1)[-1]
            stripped = stripped.rsplit("```", 1)[0].strip()

        try:
            data = json.loads(stripped)
        except json.JSONDecodeError:
            logger.warning("medium_publisher_node: LLM returned non-JSON; storing raw. raw=%r", raw[:200])
            data = {}

        medium_content = _adapt_content_for_medium(data.get("content", current_draft))
        title = data.get("title", "")
        subtitle = data.get("subtitle", "")
        tags: list[str] = data.get("tags", [])

        logger.info("Medium adaptation complete: title=%r tags=%r", title, tags)

        messages: list = list(state.get("messages", []))
        summary_lines = ["Medium-ready content has been prepared."]
        if title:
            summary_lines.append(f"\n**Title:** {title}")
        if subtitle:
            summary_lines.append(f"**Subtitle:** {subtitle}")
        if tags:
            summary_lines.append(f"**Tags:** {', '.join(tags)}")
        summary_lines.append("\nYou can copy the content from the panel on the right.")

        return {
            "medium_markdown": medium_content,
            "messages": messages + [AIMessage(content="\n".join(summary_lines))],
            "phase": "medium",
        }

    return medium_publisher_node


# ---------------------------------------------------------------------------
# linkedin_publisher node factory
# ---------------------------------------------------------------------------


def make_linkedin_publisher_node(
    llm: Any,
) -> Callable[[BlogState], Awaitable[dict[str, Any]]]:
    """Return an async LangGraph node function for generating LinkedIn content.

    The node calls the LLM with ``prompts/linkedin.md`` to produce a LinkedIn
    post and an outreach DM template.  No actual posting is performed here —
    the UI surfaces both pieces of text with clipboard copy buttons.

    Parameters
    ----------
    llm:
        An LLM instance with an async ``.ainvoke`` method.

    Returns
    -------
    An async function ``node(state: BlogState) -> dict``.
    """

    async def linkedin_publisher_node(state: BlogState) -> dict[str, Any]:
        current_draft = state.get("current_draft")
        if not current_draft:
            raise ValueError("current_draft is required in state to run linkedin_publisher node")

        system_prompt = (_PROMPTS_DIR / "linkedin.md").read_text()
        prompt = f"{system_prompt}\n\n## Blog Post\n\n{current_draft}\n\nGenerate the LinkedIn content now."

        logger.info("Generating LinkedIn content for draft (%d chars)", len(current_draft))
        response = await llm.ainvoke(prompt)
        raw = response.content if hasattr(response, "content") else str(response)

        stripped = raw.strip()
        if stripped.startswith("```"):
            stripped = stripped.split("\n", 1)[-1]
            stripped = stripped.rsplit("```", 1)[0].strip()

        try:
            data = json.loads(stripped)
        except json.JSONDecodeError:
            logger.warning(
                "linkedin_publisher_node: LLM returned non-JSON; storing raw. raw=%r", raw[:200]
            )
            data = {}

        linkedin_post = data.get("post", raw)
        outreach_dm = data.get("outreach_dm", "")

        post_length = len(linkedin_post)
        dm_length = len(outreach_dm)
        logger.info(
            "LinkedIn content generated: post=%d chars, dm=%d chars",
            post_length,
            dm_length,
        )

        messages: list = list(state.get("messages", []))
        summary = (
            "LinkedIn content has been prepared.\n\n"
            f"Post length: {post_length} characters.\n"
        )
        if outreach_dm:
            summary += f"Outreach DM length: {dm_length} characters.\n"
        summary += "\nCopy both from the panel on the right."

        return {
            "linkedin_post": linkedin_post,
            "outreach_dm": outreach_dm,
            "messages": messages + [AIMessage(content=summary)],
            "phase": "linkedin",
        }

    return linkedin_publisher_node
