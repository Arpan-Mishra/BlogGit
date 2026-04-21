"""
TDD tests for app.agent.state — BlogState TypedDict, RepoSummary and DraftVersion
frozen dataclasses.

RED phase: written before the implementation exists.
"""

import pytest
from dataclasses import FrozenInstanceError


# ---------------------------------------------------------------------------
# RepoSummary
# ---------------------------------------------------------------------------


class TestRepoSummary:
    def _make(self) -> "RepoSummary":
        from app.agent.state import RepoSummary

        return RepoSummary(
            language="Python",
            modules=("app", "tests"),
            purpose="A blog copilot that turns GitHub repos into blog posts.",
            notable_commits=("abc1234 feat: initial commit",),
            readme_excerpt="A tool that converts private GitHub work into blog posts.",
        )

    def test_fields_are_readable(self) -> None:
        s = self._make()
        assert s.language == "Python"
        assert s.modules == ("app", "tests")
        assert "blog copilot" in s.purpose
        assert len(s.notable_commits) == 1
        assert "converts" in s.readme_excerpt

    def test_is_frozen(self) -> None:
        s = self._make()
        with pytest.raises(FrozenInstanceError):
            s.language = "JavaScript"  # type: ignore[misc]

    def test_equality_by_value(self) -> None:
        from app.agent.state import RepoSummary

        a = RepoSummary(
            language="Go",
            modules=("main",),
            purpose="CLI tool.",
            notable_commits=(),
            readme_excerpt="Go CLI.",
        )
        b = RepoSummary(
            language="Go",
            modules=("main",),
            purpose="CLI tool.",
            notable_commits=(),
            readme_excerpt="Go CLI.",
        )
        assert a == b

    def test_modules_is_tuple(self) -> None:
        s = self._make()
        assert isinstance(s.modules, tuple)

    def test_notable_commits_is_tuple(self) -> None:
        s = self._make()
        assert isinstance(s.notable_commits, tuple)


# ---------------------------------------------------------------------------
# DraftVersion
# ---------------------------------------------------------------------------


class TestDraftVersion:
    def test_fields_are_readable(self) -> None:
        from app.agent.state import DraftVersion

        d = DraftVersion(version=1, content="Hello world", user_feedback="Make it shorter")
        assert d.version == 1
        assert d.content == "Hello world"
        assert d.user_feedback == "Make it shorter"

    def test_user_feedback_defaults_to_none(self) -> None:
        from app.agent.state import DraftVersion

        d = DraftVersion(version=1, content="content")
        assert d.user_feedback is None

    def test_is_frozen(self) -> None:
        from app.agent.state import DraftVersion

        d = DraftVersion(version=1, content="content")
        with pytest.raises(FrozenInstanceError):
            d.version = 2  # type: ignore[misc]

    def test_equality_by_value(self) -> None:
        from app.agent.state import DraftVersion

        a = DraftVersion(version=2, content="draft", user_feedback=None)
        b = DraftVersion(version=2, content="draft", user_feedback=None)
        assert a == b


# ---------------------------------------------------------------------------
# BlogState TypedDict
# ---------------------------------------------------------------------------


class TestBlogState:
    def test_can_construct_minimal_state(self) -> None:
        from app.agent.state import BlogState

        state: BlogState = {
            "user_id": "user-123",
            "session_id": "sess-456",
            "phase": "repo",
            "messages": [],
            "repo_url": "https://github.com/owner/repo",
            "repo_summary": None,
            "intake_answers": {},
            "current_draft": None,
            "revision_history": [],
            "notion_page_id": None,
            "notion_title": None,
            "medium_markdown": None,
            "medium_url": None,
            "linkedin_post": None,
            "linkedin_post_url": None,
            "outreach_dm": None,
        }
        assert state["phase"] == "repo"
        assert state["user_id"] == "user-123"

    def test_can_store_repo_summary(self) -> None:
        from app.agent.state import BlogState, RepoSummary

        summary = RepoSummary(
            language="TypeScript",
            modules=("src",),
            purpose="A web app.",
            notable_commits=(),
            readme_excerpt="Built with TypeScript.",
        )
        state: BlogState = {
            "user_id": "u",
            "session_id": "s",
            "phase": "intake",
            "messages": [],
            "repo_url": None,
            "repo_summary": summary,
            "intake_answers": {},
            "current_draft": None,
            "revision_history": [],
            "notion_page_id": None,
            "notion_title": None,
            "medium_markdown": None,
            "medium_url": None,
            "linkedin_post": None,
            "linkedin_post_url": None,
            "outreach_dm": None,
        }
        assert state["repo_summary"] == summary
        assert state["phase"] == "intake"
