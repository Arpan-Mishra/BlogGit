"""
TDD tests for app/api/routes/chat.py — /chat SSE endpoint.

RED phase: written before the implementation exists.

The `client` fixture (from conftest.py) provides a TestClient with dummy
settings so no real .env file is required.
"""

import pytest
from fastapi.testclient import TestClient


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
