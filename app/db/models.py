"""
Immutable DTO (Data Transfer Object) models that mirror the Supabase schema.

These are plain frozen dataclasses — no ORM magic — used to carry data
between the repository layer and the rest of the application.
"""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class OAuthConnection:
    """Represents a row in the oauth_connections table."""

    id: str
    user_id: str
    provider: str  # "github" | "notion" | "linkedin" | "medium"
    access_token_encrypted: bytes
    refresh_token_encrypted: bytes | None
    expires_at: datetime | None
    scopes: list[str] | None


@dataclass(frozen=True)
class DraftRecord:
    """Mirrors a blog_drafts row joined with sessions.user_id and sessions.title."""

    session_id: str
    user_id: str
    repo_url: str
    title: str          # sessions.title, falls back to repo_url if null
    current_draft: str
    created_at: str     # ISO timestamp string from DB
    notion_page_id: str | None = field(default=None)
    notion_title: str | None = field(default=None)
    medium_markdown: str | None = field(default=None)
    linkedin_post: str | None = field(default=None)
    outreach_dm: str | None = field(default=None)
