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

from app.db.models import OAuthConnection

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
