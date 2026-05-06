"""
Repository layer for Blog Copilot database access.

Follows the Repository Pattern via typing.Protocol so business logic
never imports Supabase directly — tests can inject a fake implementation.

Current repositories:
  - OAuthConnectionRepository (Protocol)
  - SupabaseOAuthConnectionRepository (Supabase implementation)
"""

from datetime import datetime
from typing import Any, Protocol

from app.db.models import DraftRecord, OAuthConnection

# ---------------------------------------------------------------------------
# Protocol (interface)
# ---------------------------------------------------------------------------


class OAuthConnectionRepository(Protocol):
    """Abstract interface for persisting OAuth connections."""

    def upsert(
        self,
        *,
        user_id: str,
        provider: str,
        access_token_encrypted: bytes,
        refresh_token_encrypted: bytes | None,
        expires_at: datetime | None,
        scopes: list[str] | None,
    ) -> None:
        """Insert or update the OAuth connection for (user_id, provider)."""
        ...

    def get(self, *, user_id: str, provider: str) -> OAuthConnection | None:
        """Return the connection or None if not found."""
        ...

    def delete(self, *, user_id: str, provider: str) -> None:
        """Remove the connection for (user_id, provider)."""
        ...


# ---------------------------------------------------------------------------
# Supabase implementation
# ---------------------------------------------------------------------------


class SupabaseOAuthConnectionRepository:
    """Supabase-backed implementation of OAuthConnectionRepository."""

    _TABLE = "oauth_connections"

    def __init__(self, client: Any) -> None:
        self._client = client

    def upsert(
        self,
        *,
        user_id: str,
        provider: str,
        access_token_encrypted: bytes,
        refresh_token_encrypted: bytes | None,
        expires_at: datetime | None,
        scopes: list[str] | None,
    ) -> None:
        # Fernet ciphertext is base64-ASCII — safe to decode to str for text column storage.
        payload: dict[str, Any] = {
            "user_id": user_id,
            "provider": provider,
            "access_token_encrypted": access_token_encrypted.decode("utf-8"),
            "refresh_token_encrypted": (
                refresh_token_encrypted.decode("utf-8") if refresh_token_encrypted is not None else None
            ),
            "expires_at": expires_at.isoformat() if expires_at is not None else None,
            "scopes": scopes,
        }
        (self._client.table(self._TABLE).upsert(payload, on_conflict="user_id,provider").execute())

    def get(self, *, user_id: str, provider: str) -> OAuthConnection | None:
        result = (
            self._client.table(self._TABLE)
            .select("*")
            .eq("user_id", user_id)
            .eq("provider", provider)
            .execute()
        )
        rows: list[dict[str, Any]] = result.data or []
        if not rows:
            return None
        row = rows[0]
        raw_refresh = row.get("refresh_token_encrypted")
        return OAuthConnection(
            id=row["id"],
            user_id=row["user_id"],
            provider=row["provider"],
            access_token_encrypted=row["access_token_encrypted"].encode("utf-8"),
            refresh_token_encrypted=raw_refresh.encode("utf-8") if raw_refresh is not None else None,
            expires_at=row.get("expires_at"),
            scopes=row.get("scopes"),
        )

    def delete(self, *, user_id: str, provider: str) -> None:
        (
            self._client.table(self._TABLE)
            .delete()
            .eq("user_id", user_id)
            .eq("provider", provider)
            .execute()
        )


# ---------------------------------------------------------------------------
# DraftRepository
# ---------------------------------------------------------------------------


class DraftRepository(Protocol):
    """Abstract interface for persisting blog drafts."""

    def upsert(
        self,
        *,
        session_id: str,
        user_id: str,
        repo_url: str,
        current_draft: str,
        notion_page_id: str | None = None,
        notion_title: str | None = None,
        medium_markdown: str | None = None,
        linkedin_post: str | None = None,
        outreach_dm: str | None = None,
    ) -> None:
        """Insert or update session + blog_draft rows for this session."""
        ...

    def list_by_user(self, *, user_id: str) -> list[DraftRecord]:
        """Return all drafts for a user, newest first."""
        ...

    def get_by_session(self, *, session_id: str) -> DraftRecord | None:
        """Return the draft for a session, or None if not found."""
        ...


class SupabaseDraftRepository:
    """Supabase-backed implementation of DraftRepository.

    Uses the service-role client (bypasses RLS) and applies manual user_id
    filtering to stay consistent with the auth.py route pattern.
    """

    _SESSIONS_TABLE = "sessions"
    _DRAFTS_TABLE = "blog_drafts"

    def __init__(self, client: Any) -> None:
        self._client = client

    def upsert(
        self,
        *,
        session_id: str,
        user_id: str,
        repo_url: str,
        current_draft: str,
        notion_page_id: str | None = None,
        notion_title: str | None = None,
        medium_markdown: str | None = None,
        linkedin_post: str | None = None,
        outreach_dm: str | None = None,
    ) -> None:
        title = repo_url.split("/")[-1] if repo_url else session_id
        self._client.table(self._SESSIONS_TABLE).upsert(
            {"id": session_id, "user_id": user_id, "title": title, "status": "active"},
            on_conflict="id",
        ).execute()

        draft_payload: dict[str, Any] = {
            "session_id": session_id,
            "repo_url": repo_url,
            "current_draft": current_draft,
        }
        for field_name, value in (
            ("notion_page_id", notion_page_id),
            ("notion_title", notion_title),
            ("medium_markdown", medium_markdown),
            ("linkedin_post", linkedin_post),
            ("outreach_dm", outreach_dm),
        ):
            if value is not None:
                draft_payload[field_name] = value

        self._client.table(self._DRAFTS_TABLE).upsert(
            draft_payload, on_conflict="session_id"
        ).execute()

    def list_by_user(self, *, user_id: str) -> list[DraftRecord]:
        sessions_result = (
            self._client.table(self._SESSIONS_TABLE)
            .select("id, title")
            .eq("user_id", user_id)
            .execute()
        )
        session_rows: list[dict[str, Any]] = sessions_result.data or []
        if not session_rows:
            return []

        session_ids = [r["id"] for r in session_rows]
        title_by_id = {r["id"]: r.get("title") for r in session_rows}

        drafts_result = (
            self._client.table(self._DRAFTS_TABLE)
            .select("session_id, repo_url, current_draft, created_at, notion_page_id, notion_title, medium_markdown, linkedin_post, outreach_dm")
            .in_("session_id", session_ids)
            .order("updated_at", desc=True)
            .execute()
        )
        draft_rows: list[dict[str, Any]] = drafts_result.data or []

        records: list[DraftRecord] = []
        for row in draft_rows:
            sid = row["session_id"]
            raw_title = title_by_id.get(sid) or row.get("repo_url", sid)
            records.append(
                DraftRecord(
                    session_id=sid,
                    user_id=user_id,
                    repo_url=row.get("repo_url", ""),
                    title=raw_title,
                    current_draft=row.get("current_draft", ""),
                    created_at=row.get("created_at", ""),
                    notion_page_id=row.get("notion_page_id"),
                    notion_title=row.get("notion_title"),
                    medium_markdown=row.get("medium_markdown"),
                    linkedin_post=row.get("linkedin_post"),
                    outreach_dm=row.get("outreach_dm"),
                )
            )
        return records

    def get_by_session(self, *, session_id: str) -> DraftRecord | None:
        draft_result = (
            self._client.table(self._DRAFTS_TABLE)
            .select("session_id, repo_url, current_draft, created_at, notion_page_id, notion_title, medium_markdown, linkedin_post, outreach_dm")
            .eq("session_id", session_id)
            .execute()
        )
        draft_rows: list[dict[str, Any]] = draft_result.data or []
        if not draft_rows:
            return None
        row = draft_rows[0]

        session_result = (
            self._client.table(self._SESSIONS_TABLE)
            .select("user_id, title")
            .eq("id", session_id)
            .execute()
        )
        session_rows: list[dict[str, Any]] = session_result.data or []
        if not session_rows:
            return None
        session_row = session_rows[0]

        raw_title = session_row.get("title") or row.get("repo_url", session_id)
        return DraftRecord(
            session_id=session_id,
            user_id=session_row["user_id"],
            repo_url=row.get("repo_url", ""),
            title=raw_title,
            current_draft=row.get("current_draft", ""),
            created_at=row.get("created_at", ""),
            notion_page_id=row.get("notion_page_id"),
            notion_title=row.get("notion_title"),
            medium_markdown=row.get("medium_markdown"),
            linkedin_post=row.get("linkedin_post"),
            outreach_dm=row.get("outreach_dm"),
        )
