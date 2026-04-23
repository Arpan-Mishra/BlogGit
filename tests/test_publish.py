"""
Tests for app/api/routes/publish.py — /publish/notion, /publish/medium,
/publish/linkedin endpoints, and publisher node factories in nodes.py.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.agent.state import BlogState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_state(draft: str = "# Test Post\n\nContent here.") -> BlogState:
    return BlogState(
        user_id="user-1",
        session_id="sess-1",
        phase="revise",
        messages=[],
        repo_url="https://github.com/owner/repo",
        repo_summary=None,
        intake_answers={},
        outline_plan=None,
        user_citations=(),
        current_draft=draft,
        revision_history=[],
        notion_page_id=None,
        notion_title=None,
        medium_markdown=None,
        medium_url=None,
        linkedin_post=None,
        linkedin_post_url=None,
        outreach_dm=None,
    )


# ---------------------------------------------------------------------------
# Notion publisher node
# ---------------------------------------------------------------------------


class TestNotionPublisherNode:
    @pytest.mark.asyncio
    async def test_publishes_page_and_returns_state_update(self) -> None:
        from app.agent.nodes import make_notion_publisher_node

        with patch(
            "app.tools.notion_mcp.create_notion_page",
            new_callable=AsyncMock,
            return_value="https://notion.so/abc123",
        ):
            node = make_notion_publisher_node(
                token="secret_test",
                parent_page_id="a" * 32,
            )
            result = await node(_make_state())

        assert result["notion_title"] == "Test Post"
        assert result["phase"] == "notion"
        assert len(result["messages"]) == 1
        assert "notion" in result["messages"][0].content.lower()

    @pytest.mark.asyncio
    async def test_raises_when_draft_is_missing(self) -> None:
        from app.agent.nodes import make_notion_publisher_node

        state = {**_make_state(), "current_draft": None}

        node = make_notion_publisher_node(token="t", parent_page_id="p")
        with pytest.raises(ValueError, match="current_draft"):
            await node(state)


# ---------------------------------------------------------------------------
# Medium publisher node
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# _adapt_content_for_medium helper
# ---------------------------------------------------------------------------


class TestAdaptContentForMedium:
    def test_strips_h2_headings(self) -> None:
        from app.agent.nodes import _adapt_content_for_medium

        content = "## Introduction\n\nSome text.\n\n## Conclusion\n\nDone."
        result = _adapt_content_for_medium(content)

        assert "## " not in result
        assert "Introduction" in result
        assert "Conclusion" in result

    def test_strips_h3_headings(self) -> None:
        from app.agent.nodes import _adapt_content_for_medium

        content = "### Sub-section\n\nText here."
        result = _adapt_content_for_medium(content)

        assert "### " not in result
        assert "Sub-section" in result

    def test_preserves_h1_title(self) -> None:
        from app.agent.nodes import _adapt_content_for_medium

        content = "# My Post Title\n\n## Section\n\nBody."
        result = _adapt_content_for_medium(content)

        assert result.startswith("# My Post Title")
        assert "## " not in result

    def test_replaces_mermaid_block_with_blockquote(self) -> None:
        from app.agent.nodes import _adapt_content_for_medium

        content = (
            "Some text.\n\n"
            "```mermaid\n"
            "flowchart LR\n"
            "    A[User] --> B[API] --> C[DB]\n"
            "```\n\n"
            "More text."
        )
        result = _adapt_content_for_medium(content)

        assert "```mermaid" not in result
        assert "flowchart" not in result
        assert "> *" in result
        assert "User" in result or "API" in result  # labels extracted

    def test_mermaid_fallback_description_when_no_labels(self) -> None:
        from app.agent.nodes import _adapt_content_for_medium

        content = "```mermaid\nflowchart LR\n    A --> B\n```"
        result = _adapt_content_for_medium(content)

        assert "```mermaid" not in result
        assert "> *" in result
        assert "Architecture" in result

    def test_no_change_when_content_is_plain(self) -> None:
        from app.agent.nodes import _adapt_content_for_medium

        content = "# Title\n\nJust a paragraph with **bold** and *italics*."
        assert _adapt_content_for_medium(content) == content


class TestMediumPublisherNode:
    def _make_llm_response(self, content: str) -> MagicMock:
        response = MagicMock()
        response.content = content
        return response

    @pytest.mark.asyncio
    async def test_adapts_draft_and_returns_medium_markdown(self) -> None:
        import json
        from app.agent.nodes import make_medium_publisher_node

        payload = {
            "title": "Medium Title",
            "subtitle": "A great subtitle",
            "tags": ["Python", "Tutorial"],
            "content": "# Medium Title\n\nAdapted content.",
        }
        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(
            return_value=self._make_llm_response(json.dumps(payload))
        )

        node = make_medium_publisher_node(mock_llm)
        result = await node(_make_state())

        assert result["medium_markdown"] == payload["content"]
        assert result["phase"] == "medium"
        assert len(result["messages"]) == 1

    @pytest.mark.asyncio
    async def test_strips_headings_from_llm_content(self) -> None:
        import json
        from app.agent.nodes import make_medium_publisher_node

        raw_content = (
            "# Title\n\n"
            "## Introduction\n\n"
            "Some text.\n\n"
            "![Diagram](https://mermaid.ink/img/abc123)\n\n"
            "### Details\n\nMore text."
        )
        payload = {"title": "T", "subtitle": "S", "tags": [], "content": raw_content}
        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(
            return_value=self._make_llm_response(json.dumps(payload))
        )

        node = make_medium_publisher_node(mock_llm)
        result = await node(_make_state())

        adapted = result["medium_markdown"]
        assert "## " not in adapted
        assert "### " not in adapted
        assert "![Diagram](https://mermaid.ink/img/abc123)" in adapted

    @pytest.mark.asyncio
    async def test_pre_renders_mermaid_before_llm_call(self) -> None:
        import json
        from app.agent.nodes import make_medium_publisher_node

        payload = {"title": "T", "subtitle": "S", "tags": [], "content": "Adapted."}
        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(
            return_value=self._make_llm_response(json.dumps(payload))
        )

        state = _make_state()
        state["current_draft"] = (
            "Intro.\n\n"
            "```mermaid\ngraph LR\n  A-->B\n```\n\n"
            "End."
        )
        node = make_medium_publisher_node(mock_llm)
        await node(state)

        prompt_sent = mock_llm.ainvoke.call_args[0][0]
        assert "```mermaid" not in prompt_sent
        assert "mermaid.ink" in prompt_sent

    @pytest.mark.asyncio
    async def test_falls_back_to_adapted_original_draft_on_invalid_json(self) -> None:
        from app.agent.nodes import _adapt_content_for_medium, make_medium_publisher_node

        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(
            return_value=self._make_llm_response("not valid json at all")
        )

        original_draft = "# Test Post\n\n## Section\n\nContent here."
        node = make_medium_publisher_node(mock_llm)
        result = await node(_make_state(draft=original_draft))

        # Falls back to adapted original draft when JSON parsing fails
        assert result["medium_markdown"] == _adapt_content_for_medium(original_draft)

    @pytest.mark.asyncio
    async def test_strips_markdown_fences_from_llm_response(self) -> None:
        import json
        from app.agent.nodes import make_medium_publisher_node

        payload = {"title": "T", "subtitle": "S", "tags": [], "content": "adapted"}
        fenced = f"```json\n{json.dumps(payload)}\n```"

        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(
            return_value=self._make_llm_response(fenced)
        )

        node = make_medium_publisher_node(mock_llm)
        result = await node(_make_state())
        assert result["medium_markdown"] == "adapted"

    @pytest.mark.asyncio
    async def test_raises_when_draft_is_missing(self) -> None:
        from app.agent.nodes import make_medium_publisher_node

        state = {**_make_state(), "current_draft": None}
        mock_llm = AsyncMock()

        node = make_medium_publisher_node(mock_llm)
        with pytest.raises(ValueError, match="current_draft"):
            await node(state)


# ---------------------------------------------------------------------------
# LinkedIn publisher node
# ---------------------------------------------------------------------------


class TestLinkedInPublisherNode:
    def _make_llm_response(self, content: str) -> MagicMock:
        response = MagicMock()
        response.content = content
        return response

    @pytest.mark.asyncio
    async def test_generates_post_and_dm(self) -> None:
        import json
        from app.agent.nodes import make_linkedin_publisher_node

        payload = {
            "post": "Big insight from my latest project.\n\n#Python #OpenSource",
            "outreach_dm": "Hi {recipient_name}, I wrote about async Python. Worth a read?",
        }
        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(
            return_value=self._make_llm_response(json.dumps(payload))
        )

        node = make_linkedin_publisher_node(mock_llm)
        result = await node(_make_state())

        assert result["linkedin_post"] == payload["post"]
        assert result["outreach_dm"] == payload["outreach_dm"]
        assert result["phase"] == "linkedin"
        assert len(result["messages"]) == 1

    @pytest.mark.asyncio
    async def test_falls_back_to_raw_response_on_invalid_json(self) -> None:
        from app.agent.nodes import make_linkedin_publisher_node

        raw = "Some plain text that is not JSON"
        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(
            return_value=self._make_llm_response(raw)
        )

        node = make_linkedin_publisher_node(mock_llm)
        result = await node(_make_state())

        assert result["linkedin_post"] == raw
        assert result["outreach_dm"] == ""

    @pytest.mark.asyncio
    async def test_custom_instructions_appear_in_prompt(self) -> None:
        import json
        from app.agent.nodes import make_linkedin_publisher_node

        payload = {
            "post": "Custom post.",
            "outreach_dm": "Hi {recipient_name}, custom DM.",
        }
        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(
            return_value=self._make_llm_response(json.dumps(payload))
        )

        node = make_linkedin_publisher_node(mock_llm, custom_instructions="Focus on Python 3.12")
        await node(_make_state())

        prompt_sent = mock_llm.ainvoke.call_args[0][0]
        assert "## Custom Instructions" in prompt_sent
        assert "Focus on Python 3.12" in prompt_sent

    @pytest.mark.asyncio
    async def test_no_custom_instructions_section_when_empty(self) -> None:
        import json
        from app.agent.nodes import make_linkedin_publisher_node

        payload = {"post": "Post.", "outreach_dm": "DM."}
        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(
            return_value=self._make_llm_response(json.dumps(payload))
        )

        node = make_linkedin_publisher_node(mock_llm, custom_instructions="")
        await node(_make_state())

        prompt_sent = mock_llm.ainvoke.call_args[0][0]
        assert "## Custom Instructions" not in prompt_sent

    @pytest.mark.asyncio
    async def test_raises_when_draft_is_missing(self) -> None:
        from app.agent.nodes import make_linkedin_publisher_node

        state = {**_make_state(), "current_draft": None}
        mock_llm = AsyncMock()

        node = make_linkedin_publisher_node(mock_llm)
        with pytest.raises(ValueError, match="current_draft"):
            await node(state)


# ---------------------------------------------------------------------------
# /publish/notion endpoint
# ---------------------------------------------------------------------------


class TestNotionPublishEndpoint:
    def test_notion_endpoint_exists(self, client: TestClient) -> None:
        response = client.post("/publish/notion", json={})
        assert response.status_code != 404

    def test_missing_fields_returns_422(self, client: TestClient) -> None:
        response = client.post("/publish/notion", json={"session_id": "s1"})
        assert response.status_code == 422

    def test_unknown_session_returns_404(self, client: TestClient) -> None:
        response = client.post(
            "/publish/notion",
            json={
                "session_id": "nonexistent-session",
                "token": "secret_test",
                "parent_page_id": "a" * 32,
            },
        )
        assert response.status_code == 404

    def test_publishes_successfully(self, client: TestClient) -> None:
        from app.api.session_store import _sessions

        session_id = "test-notion-session"
        _sessions[session_id] = _make_state()

        try:
            with patch(
                "app.tools.notion_mcp.create_notion_page",
                new_callable=AsyncMock,
                return_value="https://notion.so/abc123",
            ):
                response = client.post(
                    "/publish/notion",
                    json={
                        "session_id": session_id,
                        "token": "secret_test",
                        "parent_page_id": "a" * 32,
                    },
                )
        finally:
            _sessions.pop(session_id, None)

        assert response.status_code == 200
        data = response.json()
        assert "notion_title" in data
        assert "page_url" in data

    def test_missing_draft_returns_422(self, client: TestClient) -> None:
        from app.api.session_store import _sessions

        session_id = "test-no-draft"
        _sessions[session_id] = {**_make_state(), "current_draft": None}

        try:
            response = client.post(
                "/publish/notion",
                json={
                    "session_id": session_id,
                    "token": "t",
                    "parent_page_id": "a" * 32,
                },
            )
        finally:
            _sessions.pop(session_id, None)

        assert response.status_code == 422


# ---------------------------------------------------------------------------
# /publish/medium endpoint
# ---------------------------------------------------------------------------


class TestMediumAdaptEndpoint:
    def test_medium_endpoint_exists(self, client: TestClient) -> None:
        response = client.post("/publish/medium", json={})
        assert response.status_code != 404

    def test_unknown_session_returns_404(self, client: TestClient) -> None:
        response = client.post("/publish/medium", json={"session_id": "no-such-session"})
        assert response.status_code == 404

    def test_adapts_draft_successfully(self, client: TestClient) -> None:
        import json
        from app.api.session_store import _sessions

        session_id = "test-medium-session"
        _sessions[session_id] = _make_state()

        mock_payload = json.dumps({
            "title": "T",
            "subtitle": "S",
            "tags": ["Python"],
            "content": "Adapted content.",
        })

        try:
            with patch(
                "app.api.routes.publish.ChatAnthropic",
                autospec=True,
            ) as mock_cls:
                mock_instance = MagicMock()
                mock_instance.ainvoke = AsyncMock(
                    return_value=MagicMock(content=mock_payload)
                )
                mock_cls.return_value = mock_instance

                response = client.post(
                    "/publish/medium",
                    json={"session_id": session_id},
                )
        finally:
            _sessions.pop(session_id, None)

        assert response.status_code == 200
        data = response.json()
        assert "medium_markdown" in data


# ---------------------------------------------------------------------------
# /publish/linkedin endpoint
# ---------------------------------------------------------------------------


class TestLinkedInGenerateEndpoint:
    def test_linkedin_endpoint_exists(self, client: TestClient) -> None:
        response = client.post("/publish/linkedin", json={})
        assert response.status_code != 404

    def test_unknown_session_returns_404(self, client: TestClient) -> None:
        response = client.post(
            "/publish/linkedin", json={"session_id": "no-such-session"}
        )
        assert response.status_code == 404

    def test_generates_content_successfully(self, client: TestClient) -> None:
        import json
        from app.api.session_store import _sessions

        session_id = "test-linkedin-session"
        _sessions[session_id] = _make_state()

        mock_payload = json.dumps({
            "post": "My LinkedIn post content.",
            "outreach_dm": "Hi {recipient_name}, check this out!",
        })

        try:
            with patch(
                "app.api.routes.publish.ChatAnthropic",
                autospec=True,
            ) as mock_cls:
                mock_instance = MagicMock()
                mock_instance.ainvoke = AsyncMock(
                    return_value=MagicMock(content=mock_payload)
                )
                mock_cls.return_value = mock_instance

                response = client.post(
                    "/publish/linkedin",
                    json={"session_id": session_id},
                )
        finally:
            _sessions.pop(session_id, None)

        assert response.status_code == 200
        data = response.json()
        assert "linkedin_post" in data
        assert "outreach_dm" in data

    def test_custom_instructions_passed_through(self, client: TestClient) -> None:
        import json
        from app.api.session_store import _sessions

        session_id = "test-linkedin-custom"
        _sessions[session_id] = _make_state()

        mock_payload = json.dumps({
            "post": "Custom post.",
            "outreach_dm": "Hi {recipient_name}, custom!",
        })

        try:
            with patch(
                "app.api.routes.publish.ChatAnthropic",
                autospec=True,
            ) as mock_cls:
                mock_instance = MagicMock()
                mock_instance.ainvoke = AsyncMock(
                    return_value=MagicMock(content=mock_payload)
                )
                mock_cls.return_value = mock_instance

                response = client.post(
                    "/publish/linkedin",
                    json={
                        "session_id": session_id,
                        "custom_instructions": "Keep it casual",
                    },
                )

                prompt_sent = mock_instance.ainvoke.call_args[0][0]
                assert "Keep it casual" in prompt_sent
        finally:
            _sessions.pop(session_id, None)

        assert response.status_code == 200
