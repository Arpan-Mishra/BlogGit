"""
Immutable DTO (Data Transfer Object) models that mirror the Supabase schema.

These are plain frozen dataclasses — no ORM magic — used to carry data
between the repository layer and the rest of the application.
"""

from dataclasses import dataclass
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
