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
# _make_exploration_llm and _make_synthesis_llm
# ---------------------------------------------------------------------------


class TestMakeLlmFactories:
    def _make_settings(self) -> MagicMock:
        settings = MagicMock()
        settings.anthropic_model = "claude-test"
        settings.anthropic_api_key.get_secret_value.return_value = "sk-test"
        return settings

    def test_exploration_llm_returns_chat_anthropic(self) -> None:
        from app.api.routes.chat import _make_exploration_llm

        mock_instance = MagicMock()
        with patch("app.api.routes.chat.ChatAnthropic", return_value=mock_instance) as MockCls:
            result = _make_exploration_llm(self._make_settings())
            MockCls.assert_called_once()
            call_kwargs = MockCls.call_args[1]
            assert call_kwargs["max_tokens"] == 512
        assert result is mock_instance

    def test_synthesis_llm_returns_chat_anthropic(self) -> None:
        from app.api.routes.chat import _make_synthesis_llm

        mock_instance = MagicMock()
        with patch("app.api.routes.chat.ChatAnthropic", return_value=mock_instance) as MockCls:
            result = _make_synthesis_llm(self._make_settings())
            MockCls.assert_called_once()
            call_kwargs = MockCls.call_args[1]
            assert call_kwargs["max_tokens"] == 2048
        assert result is mock_instance

    def test_exploration_llm_uses_settings_model(self) -> None:
        from app.api.routes.chat import _make_exploration_llm

        settings = self._make_settings()
        settings.anthropic_model = "claude-opus-4-6"

        with patch("app.api.routes.chat.ChatAnthropic") as MockCls:
            _make_exploration_llm(settings)
            call_kwargs = MockCls.call_args[1]
            assert call_kwargs["model"] == "claude-opus-4-6"

    def test_synthesis_llm_uses_settings_model(self) -> None:
        from app.api.routes.chat import _make_synthesis_llm

        settings = self._make_settings()
        settings.anthropic_model = "claude-sonnet-4-6"

        with patch("app.api.routes.chat.ChatAnthropic") as MockCls:
            _make_synthesis_llm(settings)
            call_kwargs = MockCls.call_args[1]
            assert call_kwargs["model"] == "claude-sonnet-4-6"
