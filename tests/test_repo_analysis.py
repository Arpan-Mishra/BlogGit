"""
TDD tests for app/agent/_repo_analysis.py — three-phase repo analysis pipeline.

All GitHub tools are mocked with AsyncMock so no real network calls are made.
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tool(name: str, return_value: str = "") -> MagicMock:
    tool = MagicMock()
    tool.name = name
    tool.ainvoke = AsyncMock(return_value=return_value)
    return tool


def _make_all_tools(
    readme: str = "# README",
    tree: str = "src/main.py\ntests/test_main.py",
    commits: str = "abc1234 feat: initial",
    metadata: str = "Language: Python",
    file_contents: str = "def main(): pass",
    search_result: str = "FILE: src/main.py\n  def main(): pass",
) -> list:
    return [
        _make_tool("get_readme", readme),
        _make_tool("get_file_tree", tree),
        _make_tool("get_recent_commits", commits),
        _make_tool("get_repo_metadata", metadata),
        _make_tool("get_file_contents", file_contents),
        _make_tool("search_code", search_result),
    ]


def _make_exploration_llm(
    files: list | None = None, queries: list | None = None
) -> MagicMock:
    plan = {
        "files_to_fetch": files or ["src/main.py"],
        "search_queries": queries or ["def main"],
        "reasoning": "Entry point is most relevant.",
    }
    response = MagicMock()
    response.content = json.dumps(plan)
    llm = MagicMock()
    llm.ainvoke = AsyncMock(return_value=response)
    return llm


def _make_synthesis_llm(overrides: dict | None = None) -> MagicMock:
    data = {
        "language": "Python",
        "modules": ["src"],
        "purpose": "A CLI tool for doing things.",
        "notable_commits": ["abc1234 feat: initial"],
        "readme_excerpt": "# README",
        "key_files": ["src/main.py"],
        "code_insights": ["Uses argparse."],
        "tech_stack": ["Python", "argparse"],
        "architecture_notes": "Single module CLI.",
        "user_intent": "Write about the CLI.",
    }
    if overrides:
        data.update(overrides)
    response = MagicMock()
    response.content = json.dumps(data)
    llm = MagicMock()
    llm.ainvoke = AsyncMock(return_value=response)
    return llm


# ---------------------------------------------------------------------------
# BaselineData and ExplorationData
# ---------------------------------------------------------------------------


class TestDataContainers:
    def test_baseline_data_is_frozen(self) -> None:
        from app.agent._repo_analysis import BaselineData

        baseline = BaselineData(
            readme="# README",
            file_tree="src/main.py",
            commits_log="abc feat: init",
            repo_metadata="Language: Python",
        )
        with pytest.raises((AttributeError, TypeError)):
            baseline.readme = "changed"  # type: ignore[misc]

    def test_exploration_data_defaults_to_empty_dicts(self) -> None:
        from app.agent._repo_analysis import ExplorationData

        data = ExplorationData()
        assert data.file_contents == {}
        assert data.search_results == {}

    def test_exploration_plan_defaults_are_empty(self) -> None:
        from app.agent._repo_analysis import ExplorationPlan

        plan = ExplorationPlan()
        assert plan.files_to_fetch == []
        assert plan.search_queries == []
        assert plan.reasoning == ""


# ---------------------------------------------------------------------------
# phase1_fetch
# ---------------------------------------------------------------------------


class TestPhase1Fetch:
    @pytest.mark.asyncio
    async def test_returns_baseline_data(self) -> None:
        from app.agent._repo_analysis import BaselineData, phase1_fetch

        tools = _make_all_tools(readme="# My Repo", tree="src/main.py")
        result = await phase1_fetch("owner", "repo", tools)

        assert isinstance(result, BaselineData)
        assert result.readme == "# My Repo"
        assert result.file_tree == "src/main.py"

    @pytest.mark.asyncio
    async def test_all_tools_called_in_parallel(self) -> None:
        from app.agent._repo_analysis import phase1_fetch

        tools = _make_all_tools()
        await phase1_fetch("owner", "repo", tools)

        tool_map = {t.name: t for t in tools}
        tool_map["get_readme"].ainvoke.assert_called_once()
        tool_map["get_file_tree"].ainvoke.assert_called_once()
        tool_map["get_recent_commits"].ainvoke.assert_called_once()
        tool_map["get_repo_metadata"].ainvoke.assert_called_once()

    @pytest.mark.asyncio
    async def test_tree_tool_called_with_max_entries_2000(self) -> None:
        from app.agent._repo_analysis import phase1_fetch

        tools = _make_all_tools()
        await phase1_fetch("owner", "repo", tools)

        tree_tool = next(t for t in tools if t.name == "get_file_tree")
        call_args = tree_tool.ainvoke.call_args[0][0]
        assert call_args.get("max_entries") == 2000

    @pytest.mark.asyncio
    async def test_gracefully_handles_tool_failure(self) -> None:
        from app.agent._repo_analysis import phase1_fetch

        tools = _make_all_tools()
        # Make readme tool raise
        readme_tool = next(t for t in tools if t.name == "get_readme")
        readme_tool.ainvoke = AsyncMock(side_effect=RuntimeError("network error"))

        result = await phase1_fetch("owner", "repo", tools)

        assert result.readme == ""  # gracefully degraded
        assert result.file_tree != ""  # other tools still worked

    @pytest.mark.asyncio
    async def test_missing_tool_returns_empty_string(self) -> None:
        from app.agent._repo_analysis import phase1_fetch

        # Only provide tree and commits — no readme or metadata
        tools = [
            _make_tool("get_file_tree", "src/main.py"),
            _make_tool("get_recent_commits", "abc feat: init"),
        ]
        result = await phase1_fetch("owner", "repo", tools)

        assert result.readme == ""
        assert result.repo_metadata == ""
        assert result.file_tree == "src/main.py"


# ---------------------------------------------------------------------------
# phase2_explore
# ---------------------------------------------------------------------------


class TestPhase2Explore:
    @pytest.mark.asyncio
    async def test_returns_exploration_data(self) -> None:
        from app.agent._repo_analysis import BaselineData, ExplorationData, phase2_explore

        baseline = BaselineData(
            readme="# README",
            file_tree="src/main.py",
            commits_log="abc feat: init",
            repo_metadata="Language: Python",
        )
        tools = _make_all_tools()
        llm = _make_exploration_llm(files=["src/main.py"], queries=["def main"])

        result = await phase2_explore("owner", "repo", tools, baseline, "CLI tool", llm)

        assert isinstance(result, ExplorationData)
        assert "src/main.py" in result.file_contents
        assert "def main" in result.search_results

    @pytest.mark.asyncio
    async def test_enforces_cap_on_files(self) -> None:
        from app.agent._repo_analysis import BaselineData, phase2_explore

        baseline = BaselineData(
            readme="", file_tree="", commits_log="", repo_metadata=""
        )
        tools = _make_all_tools()
        # LLM tries to return 10 files — should be capped at 5
        many_files = [f"file{i}.py" for i in range(10)]
        llm = _make_exploration_llm(files=many_files, queries=[])

        result = await phase2_explore("owner", "repo", tools, baseline, "test", llm)

        assert len(result.file_contents) <= 5

    @pytest.mark.asyncio
    async def test_enforces_cap_on_queries(self) -> None:
        from app.agent._repo_analysis import BaselineData, phase2_explore

        baseline = BaselineData(
            readme="", file_tree="", commits_log="", repo_metadata=""
        )
        tools = _make_all_tools()
        many_queries = [f"query{i}" for i in range(10)]
        llm = _make_exploration_llm(files=[], queries=many_queries)

        result = await phase2_explore("owner", "repo", tools, baseline, "test", llm)

        assert len(result.search_results) <= 3

    @pytest.mark.asyncio
    async def test_handles_invalid_json_from_llm(self) -> None:
        from app.agent._repo_analysis import BaselineData, ExplorationData, phase2_explore

        baseline = BaselineData(
            readme="", file_tree="", commits_log="", repo_metadata=""
        )
        tools = _make_all_tools()
        bad_response = MagicMock()
        bad_response.content = "not json at all"
        llm = MagicMock()
        llm.ainvoke = AsyncMock(return_value=bad_response)

        result = await phase2_explore("owner", "repo", tools, baseline, "test", llm)

        # Falls back to empty plan — no files fetched, no queries run
        assert isinstance(result, ExplorationData)
        assert result.file_contents == {}
        assert result.search_results == {}


# ---------------------------------------------------------------------------
# phase3_synthesize
# ---------------------------------------------------------------------------


class TestPhase3Synthesize:
    @pytest.mark.asyncio
    async def test_returns_repo_summary(self) -> None:
        from app.agent._repo_analysis import BaselineData, ExplorationData, phase3_synthesize
        from app.agent.state import RepoSummary

        baseline = BaselineData(
            readme="# README",
            file_tree="src/main.py",
            commits_log="abc feat: init",
            repo_metadata="Language: Python",
        )
        exploration = ExplorationData(
            file_contents={"src/main.py": "def main(): pass"},
            search_results={"def main": "FILE: src/main.py"},
        )
        llm = _make_synthesis_llm()

        result = await phase3_synthesize("owner", "repo", baseline, exploration, "CLI tool", llm)

        assert isinstance(result, RepoSummary)
        assert result.language == "Python"
        assert result.purpose != ""
        assert isinstance(result.key_files, tuple)
        assert isinstance(result.tech_stack, tuple)
        assert isinstance(result.code_insights, tuple)

    @pytest.mark.asyncio
    async def test_falls_back_to_defaults_on_json_error(self) -> None:
        from app.agent._repo_analysis import BaselineData, ExplorationData, phase3_synthesize
        from app.agent.state import RepoSummary

        baseline = BaselineData(
            readme="# README excerpt",
            file_tree="src/main.py",
            commits_log="",
            repo_metadata="",
        )
        exploration = ExplorationData()

        bad_response = MagicMock()
        bad_response.content = "not valid json"
        llm = MagicMock()
        llm.ainvoke = AsyncMock(return_value=bad_response)

        result = await phase3_synthesize("owner", "repo", baseline, exploration, "test", llm)

        assert isinstance(result, RepoSummary)
        assert result.language == "unknown"
        # readme_excerpt falls back to first 500 chars of baseline.readme
        assert "README" in result.readme_excerpt

    @pytest.mark.asyncio
    async def test_strips_markdown_fences_from_llm_output(self) -> None:
        from app.agent._repo_analysis import BaselineData, ExplorationData, phase3_synthesize
        from app.agent.state import RepoSummary

        baseline = BaselineData(readme="", file_tree="", commits_log="", repo_metadata="")
        exploration = ExplorationData()

        data = {
            "language": "Go",
            "modules": [],
            "purpose": "A web server.",
            "notable_commits": [],
            "readme_excerpt": "",
            "key_files": [],
            "code_insights": [],
            "tech_stack": ["Go"],
            "architecture_notes": "",
            "user_intent": "",
        }
        fenced = f"```json\n{json.dumps(data)}\n```"
        response = MagicMock()
        response.content = fenced
        llm = MagicMock()
        llm.ainvoke = AsyncMock(return_value=response)

        result = await phase3_synthesize("owner", "repo", baseline, exploration, "test", llm)

        assert isinstance(result, RepoSummary)
        assert result.language == "Go"
        assert "Go" in result.tech_stack

    @pytest.mark.asyncio
    async def test_enriched_fields_populated_from_llm(self) -> None:
        from app.agent._repo_analysis import BaselineData, ExplorationData, phase3_synthesize

        baseline = BaselineData(readme="", file_tree="", commits_log="", repo_metadata="")
        exploration = ExplorationData()

        llm = _make_synthesis_llm(
            {
                "key_files": ["src/main.py", "src/auth.py"],
                "code_insights": ["JWT auth", "rate limiting"],
                "tech_stack": ["Python", "FastAPI", "Supabase"],
                "architecture_notes": "Layered architecture with service pattern.",
            }
        )

        result = await phase3_synthesize("owner", "repo", baseline, exploration, "test", llm)

        assert "src/main.py" in result.key_files
        assert "JWT auth" in result.code_insights
        assert "FastAPI" in result.tech_stack
        assert "Layered" in result.architecture_notes
