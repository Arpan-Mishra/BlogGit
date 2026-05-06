"""
FastAPI /drafts endpoints — list and fetch persisted blog drafts.

GET /drafts            — list all drafts for the authenticated user
GET /drafts/{session_id} — fetch a single draft and re-hydrate _sessions

Re-hydration: loading a past draft writes a minimal BlogState back into the
in-memory _sessions dict so that the existing /publish/* endpoints work
without modification.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from supabase import create_client

from app.agent.state import BlogState
from app.api.dependencies import get_current_user
from app.api.session_store import _sessions
from app.config import Settings, get_settings
from app.db.models import DraftRecord
from app.db.repositories import SupabaseDraftRepository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/drafts", tags=["drafts"])


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class DraftListItem(BaseModel):
    session_id: str
    repo_url: str
    title: str
    created_at: str
    has_notion: bool
    has_medium: bool
    has_linkedin: bool


class DraftDetail(BaseModel):
    session_id: str
    repo_url: str
    title: str
    current_draft: str
    notion_page_id: str | None
    notion_title: str | None
    medium_markdown: str | None
    linkedin_post: str | None
    outreach_dm: str | None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_repo(settings: Settings) -> SupabaseDraftRepository:
    client = create_client(
        settings.supabase_url,
        settings.supabase_service_role_key.get_secret_value(),
    )
    return SupabaseDraftRepository(client)


def _record_to_blog_state(record: DraftRecord) -> BlogState:
    """Build a minimal BlogState from a DraftRecord for publish re-use."""
    return BlogState(
        user_id=record.user_id,
        session_id=record.session_id,
        phase="done",
        messages=[],
        repo_url=record.repo_url,
        repo_summary=None,
        intake_answers={},
        outline_plan=None,
        user_citations=(),
        current_draft=record.current_draft,
        revision_history=[],
        notion_page_id=record.notion_page_id,
        notion_title=record.notion_title,
        medium_markdown=record.medium_markdown,
        medium_url=None,
        linkedin_post=record.linkedin_post,
        linkedin_post_url=None,
        outreach_dm=record.outreach_dm,
    )


# ---------------------------------------------------------------------------
# GET /drafts
# ---------------------------------------------------------------------------


@router.get("", response_model=list[DraftListItem])
async def list_drafts(
    user_id: str = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> list[DraftListItem]:
    """Return all persisted drafts for the authenticated user, newest first."""
    repo = _make_repo(settings)
    try:
        records = repo.list_by_user(user_id=user_id)
    except Exception as exc:
        logger.exception("Failed to list drafts for user %s", user_id)
        raise HTTPException(status_code=502, detail="Failed to load drafts") from exc

    return [
        DraftListItem(
            session_id=r.session_id,
            repo_url=r.repo_url,
            title=r.title,
            created_at=r.created_at,
            has_notion=r.notion_page_id is not None,
            has_medium=r.medium_markdown is not None,
            has_linkedin=r.linkedin_post is not None,
        )
        for r in records
    ]


# ---------------------------------------------------------------------------
# GET /drafts/{session_id}
# ---------------------------------------------------------------------------


@router.get("/{session_id}", response_model=DraftDetail)
async def get_draft(
    session_id: str,
    user_id: str = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> DraftDetail:
    """Fetch a single draft and re-hydrate the in-memory session store.

    Re-hydration allows the existing /publish/* endpoints to operate on a
    past draft without any modification.
    """
    repo = _make_repo(settings)
    try:
        record = repo.get_by_session(session_id=session_id)
    except Exception as exc:
        logger.exception("Failed to fetch draft for session %s", session_id)
        raise HTTPException(status_code=502, detail="Failed to load draft") from exc

    if record is None or record.user_id != user_id:
        raise HTTPException(status_code=404, detail="Draft not found")

    _sessions[session_id] = _record_to_blog_state(record)

    return DraftDetail(
        session_id=record.session_id,
        repo_url=record.repo_url,
        title=record.title,
        current_draft=record.current_draft,
        notion_page_id=record.notion_page_id,
        notion_title=record.notion_title,
        medium_markdown=record.medium_markdown,
        linkedin_post=record.linkedin_post,
        outreach_dm=record.outreach_dm,
    )
