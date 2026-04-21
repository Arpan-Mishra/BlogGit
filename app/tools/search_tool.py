"""
Web search tool factory for Blog Copilot.

build_search_tool() returns a TavilySearch tool that the drafting node
can use to look up articles and context on topics mentioned in the
repository or requested via intake answers.
"""

from langchain_tavily import TavilySearch

_MAX_RESULTS = 3


def build_search_tool(api_key: str) -> TavilySearch:
    """Build a Tavily web search tool for use during blog post drafting.

    Parameters
    ----------
    api_key:
        Tavily API key. Obtain a free key at https://tavily.com.

    Returns
    -------
    A ``TavilySearch`` instance configured for use with LangChain's
    ``bind_tools`` API. The tool returns up to ``_MAX_RESULTS`` structured
    results per query (title, url, content).
    """
    return TavilySearch(
        max_results=_MAX_RESULTS,
        tavily_api_key=api_key,
    )
