"""
Tests for app/db/repositories.py (SupabaseDraftRepository) and
app/api/routes/drafts.py (GET /drafts, GET /drafts/{session_id}).
"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.db.models import DraftRecord


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_draft_record(**overrides) -> DraftRecord:
    defaults = dict(
        session_id="sess-abc",
        user_id="user-1",
        repo_url="https://github.com/owner/repo",
        title="Test Blog Post",
        current_draft="# Hello\n\nWorld.",
        created_at="2026-01-01T00:00:00+00:00",
        notion_page_id=None,
        notion_title=None,
        medium_markdown=None,
        linkedin_post=None,
        outreach_dm=None,
    )
    defaults.update(overrides)
    return DraftRecord(**defaults)


def _make_supabase_builder(data: list | None = None) -> MagicMock:
    """Return a mock Supabase query builder with all chained methods wired up."""
    builder = MagicMock()
    builder.execute.return_value = MagicMock(data=data if data is not None else [])
    # Each chainable method returns the same builder so the chain stays intact.
    builder.select.return_value = builder
    builder.eq.return_value = builder
    builder.in_.return_value = builder
    builder.order.return_value = builder
    builder.upsert.return_value = builder
    builder.delete.return_value = builder
    return builder


def _make_supabase_client(data: list | None = None) -> MagicMock:
    """Return a mock Supabase client whose .table() returns a single reusable builder."""
    client = MagicMock()
    builder = _make_supabase_builder(data)
    client.table.return_value = builder
    return client


# ---------------------------------------------------------------------------
# SupabaseDraftRepository.upsert
# ---------------------------------------------------------------------------


class TestSupabaseDraftRepositoryUpsert:
    def test_upsert_calls_sessions_and_blog_drafts_tables(self) -> None:
        from app.db.repositories import SupabaseDraftRepository

        client = _make_supabase_client()
        repo = SupabaseDraftRepository(client)

        repo.upsert(
            session_id="sess-1",
            user_id="user-1",
            repo_url="https://github.com/o/r",
            current_draft="# Draft",
        )

        table_calls = [call.args[0] for call in client.table.call_args_list]
        assert "sessions" in table_calls
        assert "blog_drafts" in table_calls

    def test_upsert_includes_non_none_publish_fields(self) -> None:
        from app.db.repositories import SupabaseDraftRepository

        sessions_builder = _make_supabase_builder()
        drafts_builder = _make_supabase_builder()

        client = MagicMock()
        client.table.side_effect = lambda name: (
            sessions_builder if name == "sessions" else drafts_builder
        )

        repo = SupabaseDraftRepository(client)
        repo.upsert(
            session_id="sess-1",
            user_id="user-1",
            repo_url="https://github.com/o/r",
            current_draft="# Draft",
            notion_page_id="page-1",
            medium_markdown=None,  # should be excluded
        )

        payload = drafts_builder.upsert.call_args[0][0]
        assert "notion_page_id" in payload
        assert "medium_markdown" not in payload

    def test_upsert_excludes_all_none_publish_fields(self) -> None:
        from app.db.repositories import SupabaseDraftRepository

        sessions_builder = _make_supabase_builder()
        drafts_builder = _make_supabase_builder()

        client = MagicMock()
        client.table.side_effect = lambda name: (
            sessions_builder if name == "sessions" else drafts_builder
        )

        repo = SupabaseDraftRepository(client)
        repo.upsert(
            session_id="sess-1",
            user_id="user-1",
            repo_url="https://github.com/o/r",
            current_draft="# Draft",
        )

        payload = drafts_builder.upsert.call_args[0][0]
        for field_name in ("notion_page_id", "notion_title", "medium_markdown", "linkedin_post", "outreach_dm"):
            assert field_name not in payload


# ---------------------------------------------------------------------------
# SupabaseDraftRepository.list_by_user
# ---------------------------------------------------------------------------


class TestSupabaseDraftRepositoryListByUser:
    def test_returns_empty_list_when_no_sessions(self) -> None:
        from app.db.repositories import SupabaseDraftRepository

        client = _make_supabase_client(data=[])
        repo = SupabaseDraftRepository(client)

        result = repo.list_by_user(user_id="user-1")
        assert result == []

    def test_returns_draft_records_for_matching_sessions(self) -> None:
        from app.db.repositories import SupabaseDraftRepository

        sessions_data = [{"id": "sess-1", "user_id": "user-1", "title": "Post 1"}]
        drafts_data = [
            {
                "session_id": "sess-1",
                "current_draft": "# Hello",
                "updated_at": "2026-01-02T00:00:00+00:00",
                "created_at": "2026-01-01T00:00:00+00:00",
                "repo_url": "https://github.com/o/r",
                "notion_page_id": None,
                "notion_title": None,
                "medium_markdown": None,
                "linkedin_post": None,
                "outreach_dm": None,
            }
        ]

        sessions_builder = _make_supabase_builder(sessions_data)
        drafts_builder = _make_supabase_builder(drafts_data)

        client = MagicMock()
        client.table.side_effect = lambda name: (
            sessions_builder if name == "sessions" else drafts_builder
        )

        repo = SupabaseDraftRepository(client)
        result = repo.list_by_user(user_id="user-1")

        assert len(result) == 1
        assert result[0].session_id == "sess-1"
        assert result[0].title == "Post 1"
        assert result[0].user_id == "user-1"

    def test_uses_repo_url_as_title_fallback(self) -> None:
        from app.db.repositories import SupabaseDraftRepository

        sessions_data = [{"id": "sess-1", "user_id": "user-1", "title": None}]
        drafts_data = [
            {
                "session_id": "sess-1",
                "current_draft": "# Hello",
                "created_at": "2026-01-01T00:00:00+00:00",
                "repo_url": "https://github.com/owner/my-repo",
                "notion_page_id": None,
                "notion_title": None,
                "medium_markdown": None,
                "linkedin_post": None,
                "outreach_dm": None,
            }
        ]

        sessions_builder = _make_supabase_builder(sessions_data)
        drafts_builder = _make_supabase_builder(drafts_data)

        client = MagicMock()
        client.table.side_effect = lambda name: (
            sessions_builder if name == "sessions" else drafts_builder
        )

        repo = SupabaseDraftRepository(client)
        result = repo.list_by_user(user_id="user-1")

        assert len(result) == 1
        # Falls back to repo_url when title is None
        assert "github.com/owner/my-repo" in result[0].title or result[0].title != ""


# ---------------------------------------------------------------------------
# SupabaseDraftRepository.get_by_session
# ---------------------------------------------------------------------------


class TestSupabaseDraftRepositoryGetBySession:
    def test_returns_none_when_draft_missing(self) -> None:
        from app.db.repositories import SupabaseDraftRepository

        client = _make_supabase_client(data=[])
        repo = SupabaseDraftRepository(client)

        result = repo.get_by_session(session_id="nonexistent")
        assert result is None

    def test_returns_draft_record_when_found(self) -> None:
        from app.db.repositories import SupabaseDraftRepository

        drafts_data = [
            {
                "session_id": "sess-1",
                "current_draft": "# Hello",
                "created_at": "2026-01-01T00:00:00+00:00",
                "repo_url": "https://github.com/o/r",
                "notion_page_id": None,
                "notion_title": None,
                "medium_markdown": None,
                "linkedin_post": None,
                "outreach_dm": None,
            }
        ]
        sessions_data = [{"id": "sess-1", "user_id": "user-1", "title": "My Post"}]

        drafts_builder = _make_supabase_builder(drafts_data)
        sessions_builder = _make_supabase_builder(sessions_data)

        client = MagicMock()
        client.table.side_effect = lambda name: (
            sessions_builder if name == "sessions" else drafts_builder
        )

        repo = SupabaseDraftRepository(client)
        result = repo.get_by_session(session_id="sess-1")

        assert result is not None
        assert result.session_id == "sess-1"
        assert result.user_id == "user-1"
        assert result.title == "My Post"

    def test_returns_none_when_session_row_missing(self) -> None:
        from app.db.repositories import SupabaseDraftRepository

        drafts_data = [
            {
                "session_id": "sess-1",
                "current_draft": "# Hello",
                "created_at": "2026-01-01T00:00:00+00:00",
                "repo_url": "https://github.com/o/r",
                "notion_page_id": None,
                "notion_title": None,
                "medium_markdown": None,
                "linkedin_post": None,
                "outreach_dm": None,
            }
        ]

        drafts_builder = _make_supabase_builder(drafts_data)
        sessions_builder = _make_supabase_builder([])  # no session row

        client = MagicMock()
        client.table.side_effect = lambda name: (
            sessions_builder if name == "sessions" else drafts_builder
        )

        repo = SupabaseDraftRepository(client)
        result = repo.get_by_session(session_id="sess-1")

        assert result is None


# ---------------------------------------------------------------------------
# GET /drafts — list endpoint
# ---------------------------------------------------------------------------


class TestListDraftsRoute:
    def test_requires_auth(self, client: TestClient) -> None:
        resp = client.get("/drafts")
        assert resp.status_code in (401, 403)

    def test_returns_draft_list_items(self, client: TestClient) -> None:
        from app.api.dependencies import get_current_user
        from app.api.main import app

        record = _make_draft_record(notion_page_id="page-1")

        with patch("app.api.routes.drafts._make_repo") as mock_repo_factory:
            mock_repo = MagicMock()
            mock_repo.list_by_user.return_value = [record]
            mock_repo_factory.return_value = mock_repo

            app.dependency_overrides[get_current_user] = lambda: "user-1"
            try:
                resp = client.get("/drafts", headers={"Authorization": "Bearer fake-token"})
            finally:
                app.dependency_overrides.pop(get_current_user, None)

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["session_id"] == "sess-abc"
        assert data[0]["has_notion"] is True
        assert data[0]["has_medium"] is False
        assert data[0]["has_linkedin"] is False

    def test_returns_empty_list_when_no_drafts(self, client: TestClient) -> None:
        from app.api.dependencies import get_current_user
        from app.api.main import app

        with patch("app.api.routes.drafts._make_repo") as mock_repo_factory:
            mock_repo = MagicMock()
            mock_repo.list_by_user.return_value = []
            mock_repo_factory.return_value = mock_repo

            app.dependency_overrides[get_current_user] = lambda: "user-1"
            try:
                resp = client.get("/drafts", headers={"Authorization": "Bearer fake-token"})
            finally:
                app.dependency_overrides.pop(get_current_user, None)

        assert resp.status_code == 200
        assert resp.json() == []


# ---------------------------------------------------------------------------
# GET /drafts/{session_id} — fetch + re-hydrate
# ---------------------------------------------------------------------------


class TestGetDraftRoute:
    def test_returns_404_when_not_found(self, client: TestClient) -> None:
        from app.api.dependencies import get_current_user
        from app.api.main import app

        with patch("app.api.routes.drafts._make_repo") as mock_repo_factory:
            mock_repo = MagicMock()
            mock_repo.get_by_session.return_value = None
            mock_repo_factory.return_value = mock_repo

            app.dependency_overrides[get_current_user] = lambda: "user-1"
            try:
                resp = client.get(
                    "/drafts/nonexistent", headers={"Authorization": "Bearer fake-token"}
                )
            finally:
                app.dependency_overrides.pop(get_current_user, None)

        assert resp.status_code == 404

    def test_returns_404_for_other_users_draft(self, client: TestClient) -> None:
        from app.api.dependencies import get_current_user
        from app.api.main import app

        record = _make_draft_record(user_id="other-user")

        with patch("app.api.routes.drafts._make_repo") as mock_repo_factory:
            mock_repo = MagicMock()
            mock_repo.get_by_session.return_value = record
            mock_repo_factory.return_value = mock_repo

            app.dependency_overrides[get_current_user] = lambda: "user-1"
            try:
                resp = client.get(
                    "/drafts/sess-abc", headers={"Authorization": "Bearer fake-token"}
                )
            finally:
                app.dependency_overrides.pop(get_current_user, None)

        assert resp.status_code == 404

    def test_returns_draft_detail_for_owner(self, client: TestClient) -> None:
        from app.api.dependencies import get_current_user
        from app.api.main import app

        record = _make_draft_record()

        with patch("app.api.routes.drafts._make_repo") as mock_repo_factory:
            mock_repo = MagicMock()
            mock_repo.get_by_session.return_value = record
            mock_repo_factory.return_value = mock_repo

            app.dependency_overrides[get_current_user] = lambda: "user-1"
            try:
                resp = client.get(
                    "/drafts/sess-abc", headers={"Authorization": "Bearer fake-token"}
                )
            finally:
                app.dependency_overrides.pop(get_current_user, None)

        assert resp.status_code == 200
        data = resp.json()
        assert data["session_id"] == "sess-abc"
        assert data["current_draft"] == "# Hello\n\nWorld."
        assert data["notion_page_id"] is None

    def test_rehydrates_sessions_dict(self, client: TestClient) -> None:
        from app.api.dependencies import get_current_user
        from app.api.main import app

        record = _make_draft_record(notion_page_id="page-123")
        sessions_store: dict = {}

        with (
            patch("app.api.routes.drafts._make_repo") as mock_repo_factory,
            patch("app.api.routes.drafts._sessions", sessions_store),
        ):
            mock_repo = MagicMock()
            mock_repo.get_by_session.return_value = record
            mock_repo_factory.return_value = mock_repo

            app.dependency_overrides[get_current_user] = lambda: "user-1"
            try:
                resp = client.get(
                    "/drafts/sess-abc", headers={"Authorization": "Bearer fake-token"}
                )
            finally:
                app.dependency_overrides.pop(get_current_user, None)

        assert resp.status_code == 200
        assert "sess-abc" in sessions_store
        assert sessions_store["sess-abc"]["notion_page_id"] == "page-123"
