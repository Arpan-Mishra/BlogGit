"""
Smoke tests for app/config.py.

The Settings class must load from environment variables and expose
typed, validated fields. These tests verify that:
  - get_settings() returns a Settings instance
  - required fields are present and correct types
  - SecretStr fields do not leak values in repr
  - lru_cache returns the same object across calls
"""

import os
from unittest.mock import patch

import pytest

ENV_DEFAULTS = {
    "ANTHROPIC_API_KEY": "sk-ant-test",
    "LANGSMITH_API_KEY": "ls-test",
    "SUPABASE_URL": "https://test.supabase.co",
    "SUPABASE_ANON_KEY": "test-anon-key",
    "SUPABASE_SERVICE_ROLE_KEY": "test-service-key",
    "BLOG_COPILOT_KEK": "dGVzdC1rZXktMzItY2hhcnMtZm9yLWZlcm5ldC10ZXN0",
    "GITHUB_CLIENT_ID": "test-github-id",
    "GITHUB_CLIENT_SECRET": "test-github-secret",
    "GITHUB_OAUTH_REDIRECT_URI": "http://localhost:8000/auth/github/callback",
    "NOTION_CLIENT_ID": "test-notion-id",
    "NOTION_CLIENT_SECRET": "test-notion-secret",
    "NOTION_OAUTH_REDIRECT_URI": "http://localhost:8000/auth/notion/callback",
    "LINKEDIN_CLIENT_ID": "test-linkedin-id",
    "LINKEDIN_CLIENT_SECRET": "test-linkedin-secret",
    "LINKEDIN_OAUTH_REDIRECT_URI": "http://localhost:8000/auth/linkedin/callback",
    "APP_SECRET_KEY": "test-secret-key-32-chars-minimum-x",
    "APP_BASE_URL": "http://localhost:8000",
}


@pytest.fixture()
def settings():
    """Return a fresh Settings instance with test env vars."""
    from app.config import Settings

    with patch.dict(os.environ, ENV_DEFAULTS, clear=True):
        yield Settings()  # type: ignore[call-arg]


def test_settings_loads(settings) -> None:
    from app.config import Settings

    assert isinstance(settings, Settings)


def test_anthropic_api_key_is_secret(settings) -> None:
    # SecretStr should not expose value in str/repr
    assert "sk-ant-test" not in str(settings.anthropic_api_key)
    assert settings.anthropic_api_key.get_secret_value() == "sk-ant-test"


def test_default_anthropic_model(settings) -> None:
    assert settings.anthropic_model == "claude-sonnet-4-6"


def test_default_intake_model(settings) -> None:
    assert settings.anthropic_intake_model == "claude-haiku-4-5-20251001"


def test_supabase_url(settings) -> None:
    assert settings.supabase_url == "https://test.supabase.co"


def test_langchain_tracing_default(settings) -> None:
    assert settings.langchain_tracing_v2 is True


def test_debug_default(settings) -> None:
    assert settings.debug is False


def test_linkedin_client_id(settings) -> None:
    assert settings.linkedin_client_id == "test-linkedin-id"


def test_linkedin_client_secret_is_secret(settings) -> None:
    assert "test-linkedin-secret" not in str(settings.linkedin_client_secret)
    assert settings.linkedin_client_secret.get_secret_value() == "test-linkedin-secret"


def test_linkedin_oauth_redirect_uri(settings) -> None:
    assert settings.linkedin_oauth_redirect_uri == "http://localhost:8000/auth/linkedin/callback"


def test_get_settings_is_cached() -> None:
    from app.config import get_settings

    with patch.dict(os.environ, ENV_DEFAULTS, clear=True):
        # Clear lru_cache so test is isolated
        get_settings.cache_clear()
        s1 = get_settings()
        s2 = get_settings()
        assert s1 is s2
        get_settings.cache_clear()
