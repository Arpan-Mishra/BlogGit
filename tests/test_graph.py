"""
TDD tests for app/agent/graph.py — route_phase, route_after_intake, build_graph.

RED phase: written before the implementation exists.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_state(phase: str = "repo", **overrides) -> dict:
    from app.agent.state import RepoSummary

    base: dict = {
        "user_id": "u1",
        "session_id": "s1",
        "phase": phase,
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
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# route_phase
# ---------------------------------------------------------------------------


class TestRoutePhase:
    def test_repo_phase_routes_to_repo_analyzer(self) -> None:
        from app.agent.graph import route_phase

        assert route_phase(_make_state("repo")) == "repo_analyzer"

    def test_intake_phase_routes_to_intake(self) -> None:
        from app.agent.graph import route_phase

        assert route_phase(_make_state("intake")) == "intake"

    def test_draft_phase_routes_to_drafting(self) -> None:
        from app.agent.graph import route_phase

        assert route_phase(_make_state("draft")) == "drafting"

    def test_unknown_phase_routes_to_end(self) -> None:
        from langgraph.graph import END

        from app.agent.graph import route_phase

        assert route_phase(_make_state("done")) == END

    def test_revise_phase_routes_to_revision(self) -> None:
        from app.agent.graph import route_phase

        assert route_phase(_make_state("revise")) == "revision"


# ---------------------------------------------------------------------------
# route_after_intake
# ---------------------------------------------------------------------------


class TestRouteAfterIntake:
    def test_draft_phase_routes_to_drafting(self) -> None:
        from app.agent.graph import route_after_intake

        assert route_after_intake(_make_state("draft")) == "drafting"

    def test_intake_phase_routes_to_end(self) -> None:
        from langgraph.graph import END

        from app.agent.graph import route_after_intake

        assert route_after_intake(_make_state("intake")) == END

    def test_any_non_draft_phase_routes_to_end(self) -> None:
        from langgraph.graph import END

        from app.agent.graph import route_after_intake

        assert route_after_intake(_make_state("revise")) == END


# ---------------------------------------------------------------------------
# build_graph
# ---------------------------------------------------------------------------


class TestBuildGraph:
    def _make_mock_tools(self) -> list:
        tool = MagicMock()
        tool.name = "get_readme"
        tool.ainvoke = AsyncMock(return_value="")
        return [tool]

    def _make_mock_llm(self) -> MagicMock:
        from app.agent.state import RepoSummary

        summary = RepoSummary(
            language="Python",
            modules=("app",),
            purpose="Test.",
            notable_commits=(),
            readme_excerpt="",
        )
        llm = MagicMock()
        llm.ainvoke = AsyncMock(return_value=summary)
        return llm

    def test_build_graph_returns_compiled_graph(self) -> None:
        from app.agent.graph import build_graph

        tools = self._make_mock_tools()
        llm = self._make_mock_llm()
        graph = build_graph(tools=tools, repo_llm=llm, drafting_llm=llm)

        # Compiled LangGraph graphs have an ainvoke method
        assert hasattr(graph, "ainvoke")

    def test_compiled_graph_has_expected_nodes(self) -> None:
        from app.agent.graph import build_graph

        tools = self._make_mock_tools()
        llm = self._make_mock_llm()
        graph = build_graph(tools=tools, repo_llm=llm, drafting_llm=llm)

        node_names = set(graph.get_graph().nodes.keys())
        assert "repo_analyzer" in node_names
        assert "intake" in node_names
        assert "drafting" in node_names
        assert "revision" in node_names

    @pytest.mark.asyncio
    async def test_graph_invoke_repo_phase_returns_intake_phase(self) -> None:
        from app.agent.nodes import make_repo_analyzer_node
        from app.agent.graph import build_graph
        from app.agent.state import RepoSummary
        from langchain_core.messages import HumanMessage

        # Use a repo_llm that returns a RepoSummary
        summary = RepoSummary(
            language="Python",
            modules=("app",),
            purpose="Test project.",
            notable_commits=(),
            readme_excerpt="",
        )
        repo_llm = MagicMock()
        repo_llm.ainvoke = AsyncMock(return_value=summary)

        from langchain_core.messages import AIMessage

        drafting_llm = MagicMock()
        drafting_llm.ainvoke = AsyncMock(return_value=AIMessage(content="Draft content."))

        tools = self._make_mock_tools()
        graph = build_graph(tools=tools, repo_llm=repo_llm, drafting_llm=drafting_llm)

        state = _make_state(
            phase="repo",
            messages=[HumanMessage(content="Analyze this repo")],
        )
        result = await graph.ainvoke(state)

        # After repo_analyzer runs, graph transitions to intake node which asks Q0
        # phase should be "intake" after the intake node runs
        assert result["phase"] == "intake"
        assert result["repo_summary"] is not None
