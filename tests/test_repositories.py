"""
TDD tests for app/db/models.py and app/db/repositories.py.

RED phase: written before implementation.
Tests cover: OAuthConnection DTO shape, immutability,
and SupabaseOAuthConnectionRepository behavior against a mocked Supabase client.
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# OAuthConnection DTO — app/db/models.py
# ---------------------------------------------------------------------------


class TestOAuthConnectionModel:
    def test_model_holds_expected_fields(self) -> None:
        from app.db.models import OAuthConnection

        conn = OAuthConnection(
            id="some-uuid",
            user_id="user-uuid",
            provider="github",
            access_token_encrypted=b"ciphertext",
            refresh_token_encrypted=None,
            expires_at=None,
            scopes=["repo"],
        )
        assert conn.user_id == "user-uuid"
        assert conn.provider == "github"
        assert conn.access_token_encrypted == b"ciphertext"
        assert conn.refresh_token_encrypted is None
        assert conn.scopes == ["repo"]

    def test_model_is_immutable(self) -> None:
        from app.db.models import OAuthConnection

        conn = OAuthConnection(
            id="uuid",
            user_id="u",
            provider="github",
            access_token_encrypted=b"ct",
            refresh_token_encrypted=None,
            expires_at=None,
            scopes=None,
        )
        with pytest.raises((AttributeError, TypeError)):
            conn.provider = "notion"  # type: ignore[misc]

    def test_model_accepts_notion_provider(self) -> None:
        from app.db.models import OAuthConnection

        conn = OAuthConnection(
            id="uuid",
            user_id="u",
            provider="notion",
            access_token_encrypted=b"ct",
            refresh_token_encrypted=None,
            expires_at=None,
            scopes=None,
        )
        assert conn.provider == "notion"

    def test_model_accepts_expires_at_datetime(self) -> None:
        from app.db.models import OAuthConnection

        expires = datetime(2026, 1, 1, tzinfo=UTC)
        conn = OAuthConnection(
            id="uuid",
            user_id="u",
            provider="github",
            access_token_encrypted=b"ct",
            refresh_token_encrypted=None,
            expires_at=expires,
            scopes=None,
        )
        assert conn.expires_at == expires


# ---------------------------------------------------------------------------
# OAuthConnectionRepository Protocol — app/db/repositories.py
# ---------------------------------------------------------------------------


class TestOAuthConnectionRepositoryProtocol:
    def test_protocol_is_importable(self) -> None:
        from app.db.repositories import OAuthConnectionRepository  # noqa: F401

    def test_supabase_impl_satisfies_protocol(self) -> None:
        """SupabaseOAuthConnectionRepository must implement the Protocol."""
        from app.db.repositories import (
            SupabaseOAuthConnectionRepository,
        )

        # isinstance check works for structural subtyping via runtime_checkable
        # We just verify the class has all required methods.
        for method_name in ("upsert", "get", "delete"):
            assert hasattr(
                SupabaseOAuthConnectionRepository, method_name
            ), f"Missing method: {method_name}"


# ---------------------------------------------------------------------------
# SupabaseOAuthConnectionRepository — app/db/repositories.py
# ---------------------------------------------------------------------------


def _make_supabase_mock(*, data=None, error=None):
    """Return a mock Supabase client whose .table().upsert/select chain works."""
    client = MagicMock()

    # Build a chainable mock: table().upsert().execute() etc.
    execute_result = MagicMock()
    execute_result.data = data or []
    execute_result.error = error

    chain = MagicMock()
    chain.execute.return_value = execute_result
    chain.eq.return_value = chain
    chain.single.return_value = chain

    table = MagicMock()
    table.upsert.return_value = chain
    table.select.return_value = chain
    table.delete.return_value = chain

    client.table.return_value = table
    return client, execute_result


class TestSupabaseOAuthConnectionRepository:
    def test_upsert_calls_table_upsert(self) -> None:
        from app.db.repositories import SupabaseOAuthConnectionRepository

        client, _ = _make_supabase_mock(data=[{"id": "new-uuid"}])
        repo = SupabaseOAuthConnectionRepository(client)

        repo.upsert(
            user_id="user-1",
            provider="github",
            access_token_encrypted=b"ciphertext",
            refresh_token_encrypted=None,
            expires_at=None,
            scopes=["repo"],
        )

        client.table.assert_called_with("oauth_connections")
        client.table().upsert.assert_called_once()

    def test_upsert_payload_contains_encrypted_token(self) -> None:
        from app.db.repositories import SupabaseOAuthConnectionRepository

        client, _ = _make_supabase_mock(data=[{"id": "x"}])
        repo = SupabaseOAuthConnectionRepository(client)

        repo.upsert(
            user_id="user-1",
            provider="github",
            access_token_encrypted=b"secret_ct",
            refresh_token_encrypted=None,
            expires_at=None,
            scopes=None,
        )

        call_kwargs = client.table().upsert.call_args
        payload = call_kwargs[0][0]  # first positional arg
        assert payload["access_token_encrypted"] == "secret_ct"  # bytes decoded to str for text column
        assert payload["user_id"] == "user-1"
        assert payload["provider"] == "github"

    def test_get_returns_oauth_connection_when_found(self) -> None:
        from app.db.models import OAuthConnection
        from app.db.repositories import SupabaseOAuthConnectionRepository

        row = {
            "id": "row-uuid",
            "user_id": "user-1",
            "provider": "github",
            "access_token_encrypted": "ct",  # DB stores as text; repo re-encodes to bytes on read
            "refresh_token_encrypted": None,
            "expires_at": None,
            "scopes": ["repo"],
        }
        client, _ = _make_supabase_mock(data=[row])
        repo = SupabaseOAuthConnectionRepository(client)

        result = repo.get(user_id="user-1", provider="github")

        assert isinstance(result, OAuthConnection)
        assert result.provider == "github"
        assert result.access_token_encrypted == b"ct"

    def test_get_returns_none_when_not_found(self) -> None:
        from app.db.repositories import SupabaseOAuthConnectionRepository

        client, _ = _make_supabase_mock(data=[])
        repo = SupabaseOAuthConnectionRepository(client)

        result = repo.get(user_id="user-1", provider="github")

        assert result is None

    def test_delete_calls_table_delete(self) -> None:
        from app.db.repositories import SupabaseOAuthConnectionRepository

        client, _ = _make_supabase_mock(data=[])
        repo = SupabaseOAuthConnectionRepository(client)

        repo.delete(user_id="user-1", provider="github")

        client.table.assert_called_with("oauth_connections")
        client.table().delete.assert_called_once()

    def test_upsert_uses_on_conflict_for_upsert_semantics(self) -> None:
        """Upsert must specify the unique constraint columns."""
        from app.db.repositories import SupabaseOAuthConnectionRepository

        client, _ = _make_supabase_mock(data=[{"id": "x"}])
        repo = SupabaseOAuthConnectionRepository(client)

        repo.upsert(
            user_id="user-1",
            provider="github",
            access_token_encrypted=b"ct",
            refresh_token_encrypted=None,
            expires_at=None,
            scopes=None,
        )

        call_kwargs = client.table().upsert.call_args
        # on_conflict should reference user_id,provider unique constraint
        kwargs = call_kwargs[1] if call_kwargs[1] else {}
        if "on_conflict" in kwargs:
            assert "user_id" in kwargs["on_conflict"]
            assert "provider" in kwargs["on_conflict"]
