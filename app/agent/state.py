"""
LangGraph state schema for Blog Copilot.

BlogState is the TypedDict that flows through the StateGraph. Two frozen
dataclasses — RepoSummary and DraftVersion — carry structured sub-data.
All state updates must return new objects; never mutate in place.
"""

from dataclasses import dataclass, field
from typing import Literal, TypedDict


@dataclass(frozen=True)
class RepoSummary:
    """Structured summary produced by the repo_analyzer node.

    All collection fields are tuples (immutable) rather than lists.
    """

    language: str
    modules: tuple[str, ...]
    purpose: str
    notable_commits: tuple[str, ...]
    readme_excerpt: str


@dataclass(frozen=True)
class DraftVersion:
    """A single snapshot of the blog post draft at a given revision."""

    version: int
    content: str
    user_feedback: str | None = field(default=None)


Phase = Literal[
    "connect",
    "repo",
    "intake",
    "draft",
    "revise",
    "notion",
    "medium",
    "linkedin",
    "done",
]


class BlogState(TypedDict):
    """Full agent state that passes between LangGraph nodes."""

    user_id: str
    session_id: str
    phase: Phase
    messages: list  # list[BaseMessage] — untyped here to avoid heavy import
    repo_url: str | None
    repo_summary: RepoSummary | None
    intake_answers: dict[str, str]
    current_draft: str | None
    revision_history: list[DraftVersion]
    notion_page_id: str | None
    notion_title: str | None
    medium_markdown: str | None
    medium_url: str | None
    linkedin_post: str | None
    linkedin_post_url: str | None
    outreach_dm: str | None
