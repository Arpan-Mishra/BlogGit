"""
LangGraph StateGraph definition for Blog Copilot.

build_graph() wires all nodes and routing logic into a compiled graph.
Route functions are module-level so they can be imported and tested
independently.
"""

import logging
from typing import Any

from langgraph.graph import END, START, StateGraph

from app.agent.nodes import make_drafting_node, make_intake_node, make_repo_analyzer_node, make_revision_node
from app.agent.state import BlogState

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Routing functions
# ---------------------------------------------------------------------------


def route_phase(state: BlogState) -> str:
    """Route from START to the appropriate node based on the current phase.

    Called by the conditional edge from START on every graph invocation.
    """
    phase = state.get("phase", "repo")
    if phase == "repo":
        return "repo_analyzer"
    if phase == "intake":
        return "intake"
    if phase == "draft":
        return "drafting"
    if phase == "revise":
        return "revision"
    logger.debug("route_phase: phase=%r → END", phase)
    return END


def route_after_intake(state: BlogState) -> str:
    """Route from the intake node to drafting (if all answers collected) or END.

    Called by the conditional edge after the intake node runs.
    """
    if state.get("phase") == "draft":
        return "drafting"
    return END


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------


def build_graph(
    tools: list[Any],
    repo_llm: Any,
    drafting_llm: Any,
    search_tool: Any = None,
    checkpointer: Any = None,
) -> Any:
    """Build and compile the Blog Copilot LangGraph StateGraph.

    Parameters
    ----------
    tools:
        GitHub MCP tools passed to make_repo_analyzer_node.
    repo_llm:
        LLM used by the repo_analyzer node for structured extraction.
    drafting_llm:
        LLM used by the drafting node for blog post generation.
    search_tool:
        Optional web search tool (e.g. TavilySearchResults). When provided,
        the drafting node may call it to look up articles on topics from the
        repo or requested via intake answers.
    checkpointer:
        Optional LangGraph checkpointer for persistent state. Pass None
        for in-memory (stateless) operation.

    Returns
    -------
    A compiled LangGraph graph ready for ainvoke / astream.
    """
    graph: StateGraph = StateGraph(BlogState)

    graph.add_node("repo_analyzer", make_repo_analyzer_node(tools=tools, llm=repo_llm))
    graph.add_node("intake", make_intake_node())
    graph.add_node("drafting", make_drafting_node(llm=drafting_llm, search_tool=search_tool))
    graph.add_node("revision", make_revision_node(llm=drafting_llm))

    graph.add_conditional_edges(
        START,
        route_phase,
        {
            "repo_analyzer": "repo_analyzer",
            "intake": "intake",
            "drafting": "drafting",
            "revision": "revision",
            END: END,
        },
    )
    graph.add_edge("repo_analyzer", "intake")
    graph.add_conditional_edges(
        "intake",
        route_after_intake,
        {
            "drafting": "drafting",
            END: END,
        },
    )
    graph.add_edge("drafting", END)
    graph.add_edge("revision", END)

    return graph.compile(checkpointer=checkpointer)
