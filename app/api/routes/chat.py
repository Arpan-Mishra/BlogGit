"""
FastAPI /chat endpoint with SSE streaming.

Architecture (Sprint 4):
  - In-memory session store (_sessions dict) replaces DB checkpointer.
  - Each POST /chat invocation appends the user message, runs the graph,
    and streams new AIMessages back as SSE events.
  - A new session is initialised on first message; repo_url is required then.
"""

import logging
import os
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from app.agent.graph import build_graph
from app.agent.state import BlogState
from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# In-memory session store (Sprint 4 — replaced by DB checkpointer in Sprint 7)
# ---------------------------------------------------------------------------

_sessions: dict[str, BlogState] = {}


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
    from langchain_anthropic import ChatAnthropic

    from app.tools.mcp_factory import build_github_tools

    github_token = request.github_token or os.environ.get("GITHUB_TOKEN", "")
    tools = build_github_tools(github_token=github_token)

    repo_llm = _make_repo_llm(settings)
    drafting_llm = ChatAnthropic(
        model=settings.anthropic_model,
        api_key=settings.anthropic_api_key.get_secret_value(),
        max_tokens=2048,
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
    from langchain_anthropic import ChatAnthropic
    from langchain_core.messages import HumanMessage as LCHumanMessage
    from langchain_core.runnables import RunnableLambda

    import json

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
            "Do not include any other text."
        )
        messages = [LCHumanMessage(content=f"{system}\n\n{prompt}")]
        response = await chat.ainvoke(messages)
        data = json.loads(response.content)
        return RepoSummary(
            language=data.get("language", "unknown"),
            modules=tuple(data.get("modules", [])),
            purpose=data.get("purpose", ""),
            notable_commits=tuple(data.get("notable_commits", [])),
            readme_excerpt=data.get("readme_excerpt", ""),
        )

    return RunnableLambda(_invoke)


# ---------------------------------------------------------------------------
# /chat endpoint
# ---------------------------------------------------------------------------


@router.post("/chat")
async def chat(
    request: ChatRequest,
    settings: Settings = Depends(get_settings),
) -> EventSourceResponse:
    """Stream blog copilot responses as Server-Sent Events.

    On a new session, repo_url is required. Subsequent turns append the user
    message to the existing state and continue the graph from where it left off.
    """
    if request.session_id not in _sessions:
        if not request.repo_url:
            raise HTTPException(
                status_code=400,
                detail="repo_url is required to start a new session",
            )
        _sessions[request.session_id] = _make_initial_state(request)

    state = _sessions[request.session_id]
    # Append incoming user message
    updated_messages = list(state["messages"]) + [HumanMessage(content=request.message)]
    state = {**state, "messages": updated_messages}

    prev_message_count = len(updated_messages)
    graph = _build_graph_for_request(request, settings)

    async def _event_generator() -> AsyncGenerator[dict, None]:
        result = await graph.ainvoke(state)
        _sessions[request.session_id] = result

        new_messages = result.get("messages", [])[prev_message_count:]
        for msg in new_messages:
            if isinstance(msg, AIMessage):
                yield {"event": "message", "data": msg.content}

        # Signal stream end
        phase = result.get("phase", "")
        yield {"event": "done", "data": phase}

    return EventSourceResponse(_event_generator())
