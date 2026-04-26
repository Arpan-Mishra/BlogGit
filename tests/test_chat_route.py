"""
TDD tests for app/api/routes/chat.py — /chat SSE endpoint.

RED phase: written before the implementation exists.

The `client` fixture (from conftest.py) provides a TestClient with dummy
settings so no real .env file is required.
"""

import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from tests.conftest import TEST_ENV


# ---------------------------------------------------------------------------
# Route existence and validation
# ---------------------------------------------------------------------------


class TestChatRoute:
    def test_chat_route_exists(self, client: TestClient) -> None:
        # POST with empty body should return 422 (validation), not 404
        response = client.post("/chat", json={})
        assert response.status_code != 404

    def test_missing_session_id_returns_422(self, client: TestClient) -> None:
        response = client.post(
            "/chat",
            json={
                "message": "hello",
                # session_id missing
            },
        )
        assert response.status_code == 422

    def test_missing_message_returns_422(self, client: TestClient) -> None:
        response = client.post(
            "/chat",
            json={
                "session_id": "sess-1",
                # message missing
            },
        )
        assert response.status_code == 422

    def test_new_session_without_repo_url_returns_400(self, client: TestClient) -> None:
        response = client.post(
            "/chat",
            json={
                "session_id": "brand-new-session-no-repo-url",
                "message": "hello",
                # repo_url missing for a new session
            },
        )
        assert response.status_code == 400

    def test_chat_request_schema_accepts_optional_fields(self) -> None:
        """ChatRequest must accept github_token and user_id as optional."""
        from app.api.routes.chat import ChatRequest

        req = ChatRequest(
            session_id="s1",
            message="hello",
            repo_url="https://github.com/owner/repo",
        )
        assert req.user_id == "anonymous"
        assert req.github_token is None


# ---------------------------------------------------------------------------
# ChatRequest model
# ---------------------------------------------------------------------------


class TestChatRequestModel:
    def test_required_fields(self) -> None:
        from app.api.routes.chat import ChatRequest

        req = ChatRequest(
            session_id="sess-1",
            message="What is this repo?",
        )
        assert req.session_id == "sess-1"
        assert req.message == "What is this repo?"

    def test_user_id_defaults_to_anonymous(self) -> None:
        from app.api.routes.chat import ChatRequest

        req = ChatRequest(session_id="s", message="m")
        assert req.user_id == "anonymous"

    def test_repo_url_defaults_to_none(self) -> None:
        from app.api.routes.chat import ChatRequest

        req = ChatRequest(session_id="s", message="m")
        assert req.repo_url is None

    def test_github_token_defaults_to_none(self) -> None:
        from app.api.routes.chat import ChatRequest

        req = ChatRequest(session_id="s", message="m")
        assert req.github_token is None


# ---------------------------------------------------------------------------
# SSE streaming event tests
# ---------------------------------------------------------------------------


def _parse_sse_events(raw: str) -> list[dict[str, str]]:
    """Parse raw SSE text into a list of {event, data} dicts."""
    events = []
    current: dict[str, str] = {}
    for line in raw.replace("\r\n", "\n").split("\n"):
        line = line.strip()
        if line.startswith("event:"):
            current["event"] = line[len("event:"):].strip()
        elif line.startswith("data:"):
            current["data"] = line[len("data:"):].strip()
        elif line == "" and current:
            events.append(current)
            current = {}
    if current:
        events.append(current)
    return events


class TestStreamingEvents:
    """Test that _event_generator emits token, tool_start, status, message, done."""

    @pytest.fixture()
    def streaming_client(self):
        from app.config import get_settings

        with patch.dict(os.environ, TEST_ENV, clear=True):
            get_settings.cache_clear()
            from app.api.main import app
            from app.api.session_store import _sessions

            _sessions.clear()

            async def _fake_astream(state, *, stream_mode=None, version=None):
                msg_chunk = MagicMock()
                msg_chunk.content = "Hello world"
                msg_chunk.tool_calls = []
                yield {
                    "type": "messages",
                    "data": (msg_chunk, {"langgraph_node": "intake"}),
                }

                tool_chunk = MagicMock()
                tool_chunk.content = ""
                tool_chunk.tool_calls = [{"name": "tavily_search"}]
                yield {
                    "type": "messages",
                    "data": (tool_chunk, {"langgraph_node": "drafting"}),
                }

                from langchain_core.messages import AIMessage

                yield {
                    "type": "updates",
                    "data": {
                        "intake": {
                            "phase": "draft",
                            "messages": list(state["messages"])
                            + [AIMessage(content="Hello world")],
                        }
                    },
                }

            fake_graph = MagicMock()
            fake_graph.astream = _fake_astream

            with patch(
                "app.api.routes.chat._build_graph_for_request",
                return_value=fake_graph,
            ):
                yield TestClient(app, raise_server_exceptions=False)

            _sessions.clear()
            get_settings.cache_clear()

    def test_stream_emits_token_events(self, streaming_client: TestClient) -> None:
        resp = streaming_client.post(
            "/chat",
            json={
                "session_id": "stream-test-1",
                "message": "hi",
                "repo_url": "https://github.com/test/repo",
            },
        )
        assert resp.status_code == 200
        events = _parse_sse_events(resp.text)
        token_events = [e for e in events if e.get("event") == "token"]
        assert len(token_events) >= 1
        assert token_events[0]["data"] == "Hello world"

    def test_stream_emits_tool_start_events(self, streaming_client: TestClient) -> None:
        resp = streaming_client.post(
            "/chat",
            json={
                "session_id": "stream-test-2",
                "message": "hi",
                "repo_url": "https://github.com/test/repo",
            },
        )
        events = _parse_sse_events(resp.text)
        tool_events = [e for e in events if e.get("event") == "tool_start"]
        assert len(tool_events) >= 1
        parsed = json.loads(tool_events[0]["data"])
        assert parsed["tool_name"] == "tavily_search"
        assert parsed["node"] == "drafting"

    def test_stream_emits_status_events(self, streaming_client: TestClient) -> None:
        resp = streaming_client.post(
            "/chat",
            json={
                "session_id": "stream-test-3",
                "message": "hi",
                "repo_url": "https://github.com/test/repo",
            },
        )
        events = _parse_sse_events(resp.text)
        status_events = [e for e in events if e.get("event") == "status"]
        assert len(status_events) >= 1

    def test_stream_emits_done_event(self, streaming_client: TestClient) -> None:
        resp = streaming_client.post(
            "/chat",
            json={
                "session_id": "stream-test-4",
                "message": "hi",
                "repo_url": "https://github.com/test/repo",
            },
        )
        events = _parse_sse_events(resp.text)
        done_events = [e for e in events if e.get("event") == "done"]
        assert len(done_events) == 1
        assert done_events[0]["data"] == "draft"

    def test_stream_persists_state(self, streaming_client: TestClient) -> None:
        streaming_client.post(
            "/chat",
            json={
                "session_id": "stream-test-5",
                "message": "hi",
                "repo_url": "https://github.com/test/repo",
            },
        )
        from app.api.session_store import _sessions

        assert "stream-test-5" in _sessions
        assert _sessions["stream-test-5"]["phase"] == "draft"
