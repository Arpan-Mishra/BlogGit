"""
MCP tool factory — builds per-user tool sets by decrypting stored tokens on demand.

This module is the bridge between the repository layer (encrypted token storage)
and the tool layer (MCP clients, StructuredTools). Business logic never touches
raw tokens; everything is mediated through get_live_token.

Typical usage in a node:
    from app.tools.mcp_factory import get_live_token, build_github_tools

    token = get_live_token(repo=conn_repo, user_id=state["user_id"],
                           provider="github", kek=settings.blog_copilot_kek)
    tools = build_github_tools(github_token=token)
"""

import logging
from typing import Any

from app.auth.encryption import decrypt_token
from app.db.repositories import OAuthConnectionRepository
from app.tools.github_mcp import build_github_tools as _build_github_tools

logger = logging.getLogger(__name__)


class TokenNotFoundError(Exception):
    """Raised when no OAuth connection exists for the given (user_id, provider)."""

    def __init__(self, provider: str) -> None:
        super().__init__(f"No OAuth token found for provider: {provider}")
        self.provider = provider


def get_live_token(
    *,
    repo: OAuthConnectionRepository,
    user_id: str,
    provider: str,
    kek: str,
) -> str:
    """Retrieve and decrypt the access token for *user_id* + *provider*.

    Parameters
    ----------
    repo:
        An OAuthConnectionRepository instance (Supabase impl or a test double).
    user_id:
        The application user identifier.
    provider:
        One of ``"github"``, ``"notion"``, ``"linkedin"``, ``"medium"``.
    kek:
        The Fernet key-encryption key (plaintext string, loaded from env).

    Returns
    -------
    Decrypted plaintext token string.

    Raises
    ------
    TokenNotFoundError
        If no connection row exists for the given (user_id, provider) pair.
    EncryptionError
        If decryption fails (wrong key, tampered ciphertext).
    """
    connection = repo.get(user_id=user_id, provider=provider)
    if connection is None:
        raise TokenNotFoundError(provider)

    plaintext = decrypt_token(connection.access_token_encrypted, kek)
    logger.debug("Token decrypted for user=%s provider=%s", user_id, provider)
    return plaintext


def build_github_tools(github_token: str) -> list[Any]:
    """Return a list of StructuredTools for GitHub, pre-bound with *github_token*.

    Delegates to app.tools.github_mcp.build_github_tools.
    """
    return _build_github_tools(github_token)
