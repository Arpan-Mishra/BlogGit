"""
OAuth2 provider configurations.

Each entry in PROVIDERS maps a provider name to a frozen ProviderConfig
holding the static, non-secret parts of the OAuth2 flow. Secrets
(client_id, client_secret, redirect_uri) are injected per-request from
Settings so they never live in this module.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderConfig:
    """Immutable static configuration for an OAuth2 provider."""

    name: str
    auth_url: str
    token_url: str
    scopes: list[str]


PROVIDERS: dict[str, ProviderConfig] = {
    "github": ProviderConfig(
        name="github",
        auth_url="https://github.com/login/oauth/authorize",
        token_url="https://github.com/login/oauth/access_token",
        scopes=["repo", "read:user", "user:email"],
    ),
    "notion": ProviderConfig(
        name="notion",
        auth_url="https://api.notion.com/v1/oauth/authorize",
        token_url="https://api.notion.com/v1/oauth/token",
        scopes=[],  # Notion uses owner-based scopes granted during authorization
    ),
    "linkedin": ProviderConfig(
        name="linkedin",
        auth_url="https://www.linkedin.com/oauth/v2/authorization",
        token_url="https://www.linkedin.com/oauth/v2/accessToken",
        scopes=["openid", "profile", "w_member_social"],
    ),
}
