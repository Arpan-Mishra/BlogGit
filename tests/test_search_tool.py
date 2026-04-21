"""
TDD tests for app/tools/search_tool.py — build_search_tool factory.

RED phase: written before the implementation exists.
"""

import pytest


class TestBuildSearchTool:
    def test_returns_tool_with_name(self) -> None:
        """build_search_tool returns an object with a .name attribute."""
        from app.tools.search_tool import build_search_tool

        tool = build_search_tool(api_key="test-key")
        assert hasattr(tool, "name")
        assert isinstance(tool.name, str)
        assert tool.name  # non-empty

    def test_tool_name_contains_tavily(self) -> None:
        """Tool name identifies it as the Tavily search tool."""
        from app.tools.search_tool import build_search_tool

        tool = build_search_tool(api_key="test-key")
        assert "tavily" in tool.name.lower()

    def test_tool_has_ainvoke(self) -> None:
        """Tool is async-invokable (required for use in LangGraph nodes)."""
        from app.tools.search_tool import build_search_tool

        tool = build_search_tool(api_key="test-key")
        assert callable(getattr(tool, "ainvoke", None))

    def test_tool_has_description(self) -> None:
        """Tool exposes a description string for LLM tool binding."""
        from app.tools.search_tool import build_search_tool

        tool = build_search_tool(api_key="test-key")
        assert hasattr(tool, "description")
        assert isinstance(tool.description, str)
        assert tool.description

    def test_max_results_is_three(self) -> None:
        """Tool is configured to return at most 3 results per query."""
        from app.tools.search_tool import build_search_tool

        tool = build_search_tool(api_key="test-key")
        assert tool.max_results == 3


class TestBuildSearchToolInputSchema:
    def test_tool_has_args_schema(self) -> None:
        """Tool has an args_schema so LangGraph can bind it to an LLM."""
        from app.tools.search_tool import build_search_tool

        tool = build_search_tool(api_key="test-key")
        assert hasattr(tool, "args_schema") or hasattr(tool, "get_input_schema")
