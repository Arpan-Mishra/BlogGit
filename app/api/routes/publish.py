"""
FastAPI /publish/* endpoints for multi-platform blog post publishing.

Each endpoint reads the session's current draft from the in-memory session
store, invokes the appropriate publisher node, and persists the updated state.

Endpoints:
    POST /publish/notion   — create a Notion page from the current draft
    POST /publish/medium   — adapt the draft for Medium (LLM-only in v1)
    POST /publish/linkedin — generate LinkedIn post + outreach DM (LLM-only)
"""

import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from langchain_anthropic import ChatAnthropic
from pydantic import BaseModel, SecretStr

from app.agent.nodes import (
    make_linkedin_publisher_node,
    make_medium_publisher_node,
    make_notion_publisher_node,
)
from app.agent.state import BlogState
from app.api.limiter import limiter
from app.api.session_store import _sessions
from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/publish", tags=["publish"])


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class NotionPublishRequest(BaseModel):
    session_id: str
    token: SecretStr
    parent_page_id: str


class NotionPublishResponse(BaseModel):
    notion_page_id: str
    notion_title: str
    page_url: str


class MediumAdaptRequest(BaseModel):
    session_id: str


class MediumAdaptResponse(BaseModel):
    medium_markdown: str


class LinkedInGenerateRequest(BaseModel):
    session_id: str
    custom_instructions: str = ""


class LinkedInGenerateResponse(BaseModel):
    linkedin_post: str
    outreach_dm: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_session(session_id: str) -> BlogState:
    """Return session state or raise 404."""
    state = _sessions.get(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
    return state


def _require_draft(state: BlogState, session_id: str) -> str:
    """Return current_draft or raise 422."""
    draft = state.get("current_draft")
    if not draft:
        raise HTTPException(
            status_code=422,
            detail=f"Session '{session_id}' has no draft. Complete the chat flow first.",
        )
    return draft


def _make_drafting_llm(settings: Settings) -> ChatAnthropic:
    return ChatAnthropic(
        model=settings.anthropic_model,
        api_key=settings.anthropic_api_key.get_secret_value(),
        max_tokens=8096,
    )


# ---------------------------------------------------------------------------
# POST /publish/notion
# ---------------------------------------------------------------------------


@router.post("/notion", response_model=NotionPublishResponse)
@limiter.limit("20/minute")
async def publish_to_notion(
    request: Request,
    body: NotionPublishRequest,
    settings: Settings = Depends(get_settings),
) -> NotionPublishResponse:
    """Create a Notion page from the session's current draft.

    The caller must supply a valid Notion integration token and the UUID of
    the parent page under which the new page will be created.
    """
    state = _require_session(body.session_id)
    _require_draft(state, body.session_id)

    node = make_notion_publisher_node(
        token=body.token.get_secret_value(),
        parent_page_id=body.parent_page_id,
    )

    try:
        update = await node(state)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except httpx.HTTPStatusError as exc:
        logger.exception("Notion API error for session %s", body.session_id)
        raise HTTPException(status_code=502, detail="Notion API request failed") from exc
    except Exception as exc:
        logger.exception("Notion publish failed for session %s", body.session_id)
        raise HTTPException(status_code=502, detail="Notion publish failed") from exc

    _sessions[body.session_id] = {**state, **update}

    page_id = update.get("notion_page_id", "")
    title = update.get("notion_title", "")
    page_url = f"https://notion.so/{page_id.replace('-', '')}" if page_id else ""

    return NotionPublishResponse(
        notion_page_id=page_id,
        notion_title=title,
        page_url=page_url,
    )


# ---------------------------------------------------------------------------
# POST /publish/medium
# ---------------------------------------------------------------------------


@router.post("/medium", response_model=MediumAdaptResponse)
@limiter.limit("20/minute")
async def adapt_for_medium(
    request: Request,
    body: MediumAdaptRequest,
    settings: Settings = Depends(get_settings),
) -> MediumAdaptResponse:
    """Adapt the current draft for Medium using the LLM.

    Returns the Medium-optimised markdown.  Actual posting to Medium is
    handled client-side (copy-paste or the Medium editor import feature).
    """
    state = _require_session(body.session_id)
    _require_draft(state, body.session_id)

    llm = _make_drafting_llm(settings)
    node = make_medium_publisher_node(llm)

    try:
        update = await node(state)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Medium adaptation failed for session %s", body.session_id)
        raise HTTPException(status_code=502, detail="Medium adaptation failed") from exc

    _sessions[body.session_id] = {**state, **update}

    medium_markdown = update.get("medium_markdown", "")
    return MediumAdaptResponse(medium_markdown=medium_markdown)


# ---------------------------------------------------------------------------
# POST /publish/linkedin
# ---------------------------------------------------------------------------


@router.post("/linkedin", response_model=LinkedInGenerateResponse)
@limiter.limit("20/minute")
async def generate_linkedin_content(
    request: Request,
    body: LinkedInGenerateRequest,
    settings: Settings = Depends(get_settings),
) -> LinkedInGenerateResponse:
    """Generate a LinkedIn post and outreach DM from the current draft.

    Returns ready-to-copy text for both pieces.  No direct LinkedIn API call
    is made in v1 — the user copies the content from the UI.
    """
    state = _require_session(body.session_id)
    _require_draft(state, body.session_id)

    llm = _make_drafting_llm(settings)
    node = make_linkedin_publisher_node(llm, custom_instructions=body.custom_instructions)

    try:
        update = await node(state)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("LinkedIn generation failed for session %s", body.session_id)
        raise HTTPException(status_code=502, detail="LinkedIn generation failed") from exc

    _sessions[body.session_id] = {**state, **update}

    return LinkedInGenerateResponse(
        linkedin_post=update.get("linkedin_post", ""),
        outreach_dm=update.get("outreach_dm", ""),
    )
