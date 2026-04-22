"""
Unit tests for helper functions in app/api/routes/chat.py.

The SSE streaming endpoint itself is not unit tested here (it requires a live
LangGraph runtime), but the pure helper functions can be fully covered.
"""

import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# _make_initial_state
# ---------------------------------------------------------------------------


class TestMakeInitialState:
    def _make_request(self, **overrides) -> "ChatRequest":  # type: ignore[name-defined]
        from app.api.routes.chat import ChatRequest

        defaults = dict(
            session_id="sess-1",
            user_id="user-1",
            message="hello",
            repo_url="https://github.com/owner/repo",
            github_token=None,
        )
        return ChatRequest(**{**defaults, **overrides})

    def test_maps_all_request_fields_to_state(self) -> None:
        from app.api.routes.chat import _make_initial_state

        req = self._make_request(session_id="s42", user_id="u99", repo_url="https://github.com/a/b")
        state = _make_initial_state(req)

        assert state["session_id"] == "s42"
        assert state["user_id"] == "u99"
        assert state["repo_url"] == "https://github.com/a/b"

    def test_initial_phase_is_repo(self) -> None:
        from app.api.routes.chat import _make_initial_state

        state = _make_initial_state(self._make_request())
        assert state["phase"] == "repo"

    def test_messages_starts_empty(self) -> None:
        from app.api.routes.chat import _make_initial_state

        state = _make_initial_state(self._make_request())
        assert state["messages"] == []

    def test_draft_and_summary_start_as_none(self) -> None:
        from app.api.routes.chat import _make_initial_state

        state = _make_initial_state(self._make_request())
        assert state["current_draft"] is None
        assert state["repo_summary"] is None

    def test_user_citations_starts_as_empty_tuple(self) -> None:
        from app.api.routes.chat import _make_initial_state

        state = _make_initial_state(self._make_request())
        assert state["user_citations"] == ()

    def test_revision_history_starts_empty(self) -> None:
        from app.api.routes.chat import _make_initial_state

        state = _make_initial_state(self._make_request())
        assert state["revision_history"] == []

    def test_publish_fields_start_as_none(self) -> None:
        from app.api.routes.chat import _make_initial_state

        state = _make_initial_state(self._make_request())
        for field in ("notion_page_id", "notion_title", "medium_markdown",
                      "medium_url", "linkedin_post", "linkedin_post_url", "outreach_dm"):
            assert state[field] is None, f"{field} should be None"


# ---------------------------------------------------------------------------
# _make_repo_llm — the inner _invoke coroutine
# ---------------------------------------------------------------------------


class TestMakeRepoLlm:
    def _make_settings(self) -> MagicMock:
        settings = MagicMock()
        settings.anthropic_model = "claude-test"
        settings.anthropic_api_key.get_secret_value.return_value = "sk-test"
        return settings

    @pytest.mark.asyncio
    async def test_returns_repo_summary_from_valid_json(self) -> None:
        from app.api.routes.chat import _make_repo_llm
        from app.agent.state import RepoSummary

        payload = {
            "language": "Python",
            "modules": ["app", "tests"],
            "purpose": "A test tool.",
            "notable_commits": ["abc fix: something"],
            "readme_excerpt": "Hello world",
        }

        mock_chat = MagicMock()
        mock_response = MagicMock()
        mock_response.content = json.dumps(payload)
        mock_chat.ainvoke = AsyncMock(return_value=mock_response)

        with patch("app.api.routes.chat.ChatAnthropic", return_value=mock_chat):
            llm = _make_repo_llm(self._make_settings())
            result = await llm.ainvoke("some prompt")

        assert isinstance(result, RepoSummary)
        assert result.language == "Python"
        assert result.modules == ("app", "tests")
        assert result.purpose == "A test tool."

    @pytest.mark.asyncio
    async def test_falls_back_gracefully_on_non_json_response(self) -> None:
        from app.api.routes.chat import _make_repo_llm
        from app.agent.state import RepoSummary

        mock_chat = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "I cannot answer that."
        mock_chat.ainvoke = AsyncMock(return_value=mock_response)

        with patch("app.api.routes.chat.ChatAnthropic", return_value=mock_chat):
            llm = _make_repo_llm(self._make_settings())
            result = await llm.ainvoke("some prompt")

        assert isinstance(result, RepoSummary)
        assert result.language == "unknown"

    @pytest.mark.asyncio
    async def test_strips_markdown_fences_before_parsing(self) -> None:
        from app.api.routes.chat import _make_repo_llm
        from app.agent.state import RepoSummary

        payload = {
            "language": "Go",
            "modules": [],
            "purpose": "A Go service.",
            "notable_commits": [],
            "readme_excerpt": "",
        }
        fenced = f"```json\n{json.dumps(payload)}\n```"

        mock_chat = MagicMock()
        mock_response = MagicMock()
        mock_response.content = fenced
        mock_chat.ainvoke = AsyncMock(return_value=mock_response)

        with patch("app.api.routes.chat.ChatAnthropic", return_value=mock_chat):
            llm = _make_repo_llm(self._make_settings())
            result = await llm.ainvoke("prompt")

        assert isinstance(result, RepoSummary)
        assert result.language == "Go"
