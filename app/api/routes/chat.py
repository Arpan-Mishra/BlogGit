"""
FastAPI /chat endpoint with SSE streaming.

Architecture (Sprint 4):
  - In-memory session store (_sessions dict) replaces DB checkpointer.
  - Each POST /chat invocation appends the user message, runs the graph,
    and streams new AIMessages back as SSE events.
  - A new session is initialised on first message; repo_url is required then.

Streaming (Sprint 9):
  - Uses stream_mode=["messages", "updates"] with version="v2" for
    token-level streaming plus node-level state updates.
  - Emits "token" events for each LLM token chunk.
  - Emits "tool_start" events when a tool call is detected.
  - Emits "status" events on node transitions.
"""

import json
import logging
import os
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException, Request
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from app.agent.graph import build_graph
from app.agent.state import BlogState
from app.api.limiter import limiter
from app.api.session_store import _sessions
from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Per-node status messages surfaced to the frontend via SSE "status" events
# ---------------------------------------------------------------------------

_NODE_STATUS: dict[str, str] = {
    "repo_analyzer": "Analysing repository...",
    "intake": "Preparing question...",
    "outline": "Planning blog sections...",
    "drafting": "Writing draft...",
    "revision": "Revising draft...",
}


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class ChatRequest(BaseModel):
    session_id: str
    user_id: str = "anonymous"
    message: str
    repo_url: str | None = None
    github_token: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_initial_state(request: ChatRequest) -> BlogState:
    """Construct a fresh BlogState for a new session."""
    return BlogState(
        user_id=request.user_id,
        session_id=request.session_id,
        phase="repo",
        messages=[],
        repo_url=request.repo_url,
        repo_summary=None,
        intake_answers={},
        outline_plan=None,
        user_citations=(),
        current_draft=None,
        revision_history=[],
        notion_page_id=None,
        notion_title=None,
        medium_markdown=None,
        medium_url=None,
        linkedin_post=None,
        linkedin_post_url=None,
        outreach_dm=None,
    )


def _build_graph_for_request(request: ChatRequest, settings: Settings):
    """Construct the LangGraph graph with real tools and LLMs."""
    from app.tools.mcp_factory import build_github_tools

    github_token = request.github_token or os.environ.get("GITHUB_TOKEN", "")
    tools = build_github_tools(github_token=github_token)

    repo_llm = _make_repo_llm(settings)
    drafting_llm = ChatAnthropic(
        model=settings.anthropic_model,
        api_key=settings.anthropic_api_key.get_secret_value(),
        max_tokens=8096,
    )

    search_tool = None
    if settings.tavily_api_key:
        from app.tools.search_tool import build_search_tool

        search_tool = build_search_tool(api_key=settings.tavily_api_key.get_secret_value())

    return build_graph(
        tools=tools,
        repo_llm=repo_llm,
        drafting_llm=drafting_llm,
        search_tool=search_tool,
    )


def _make_repo_llm(settings: Settings):
    """Build the structured-output LLM used by the repo_analyzer node."""
    import json

    from langchain_core.messages import HumanMessage as LCHumanMessage
    from langchain_core.runnables import RunnableLambda

    from app.agent.state import RepoSummary

    chat = ChatAnthropic(
        model=settings.anthropic_model,
        api_key=settings.anthropic_api_key.get_secret_value(),
        max_tokens=1024,
    )

    async def _invoke(prompt: str) -> RepoSummary:
        system = (
            "You are an expert software analyst. "
            "Respond ONLY with a JSON object with these keys: "
            "language (str), modules (list of str), purpose (str), "
            "notable_commits (list of str), readme_excerpt (str). "
            "Do not wrap the JSON in markdown code fences. "
            "Do not include any other text."
        )
        messages = [LCHumanMessage(content=f"{system}\n\n{prompt}")]
        response = await chat.ainvoke(messages)
        raw = response.content.strip()
        # Strip markdown code fences if the model wraps the JSON anyway
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1]  # drop opening fence line
            raw = raw.rsplit("```", 1)[0].strip()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("repo_llm returned non-JSON; using fallback RepoSummary. raw=%r", raw[:200])
            data = {}
        return RepoSummary(
            language=data.get("language", "unknown"),
            modules=tuple(data.get("modules", [])),
            purpose=data.get("purpose", "Repository purpose could not be determined from available data."),
            notable_commits=tuple(data.get("notable_commits", [])),
            readme_excerpt=data.get("readme_excerpt", ""),
        )

    return RunnableLambda(_invoke)


# ---------------------------------------------------------------------------
# /chat endpoint
# ---------------------------------------------------------------------------


@router.post("/chat")
@limiter.limit("10/minute")
async def chat(
    request: Request,
    body: ChatRequest,
    settings: Settings = Depends(get_settings),
) -> EventSourceResponse:
    """Stream blog copilot responses as Server-Sent Events.

    On a new session, repo_url is required. Subsequent turns append the user
    message to the existing state and continue the graph from where it left off.
    """
    if body.session_id not in _sessions:
        if not body.repo_url:
            raise HTTPException(
                status_code=400,
                detail="repo_url is required to start a new session",
            )
        _sessions[body.session_id] = _make_initial_state(body)

    state = _sessions[body.session_id]
    # Append incoming user message
    updated_messages = list(state["messages"]) + [HumanMessage(content=body.message)]
    state = {**state, "messages": updated_messages}

    prev_message_count = len(updated_messages)
    graph = _build_graph_for_request(body, settings)

    async def _event_generator() -> AsyncGenerator[dict, None]:
        accumulated: dict = dict(state)
        emitted_nodes: set[str] = set()
        try:
            async for chunk in graph.astream(
                state,
                stream_mode=["messages", "updates"],
                version="v2",
            ):
                chunk_type = chunk.get("type")
                if chunk_type == "messages":
                    msg, metadata = chunk["data"]
                    node_name = metadata.get("langgraph_node", "")

                    if node_name and node_name not in emitted_nodes:
                        status = _NODE_STATUS.get(node_name)
                        if status:
                            emitted_nodes.add(node_name)
                            logger.info("graph node started: %s", node_name)
                            yield {"event": "status", "data": status}

                    content = getattr(msg, "content", "")
                    if content:
                        yield {"event": "token", "data": content}

                    tool_calls = getattr(msg, "tool_calls", None) or []
                    for tc in tool_calls:
                        yield {
                            "event": "tool_start",
                            "data": json.dumps({
                                "tool_name": tc.get("name", ""),
                                "node": node_name,
                            }),
                        }

                elif chunk_type == "updates":
                    for node_name, node_output in chunk["data"].items():
                        if isinstance(node_output, dict):
                            accumulated.update(node_output)
        except Exception as exc:
            logger.exception("graph.astream failed: %s", exc)
            yield {"event": "error", "data": str(exc)}
            return

        _sessions[body.session_id] = accumulated

        new_messages = accumulated.get("messages", [])[prev_message_count:]
        for msg in new_messages:
            if isinstance(msg, AIMessage):
                yield {"event": "message", "data": msg.content}

        phase = accumulated.get("phase", "")
        yield {"event": "done", "data": phase}

    return EventSourceResponse(_event_generator())
