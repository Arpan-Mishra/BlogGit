"""
Shared pytest fixtures for Blog Copilot tests.

Provides a `client` fixture that wires up a FastAPI TestClient with dummy
settings so no real .env file is needed in CI.
"""

import os
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

# Minimum env vars that satisfy Settings validation.
# Values are safe dummies — no real credentials.
# BLOG_COPILOT_KEK must be a valid Fernet key (32-byte URL-safe base64).
TEST_ENV: dict[str, str] = {
    "ANTHROPIC_API_KEY": "sk-ant-test",
    "LANGSMITH_API_KEY": "ls-test",
    "LANGSMITH_PROJECT": "test",
    "SUPABASE_URL": "https://test.supabase.co",
    "SUPABASE_ANON_KEY": "test-anon-key",
    "SUPABASE_SERVICE_ROLE_KEY": "test-service-key",
    # Valid Fernet key: 32 zero-bytes encoded as URL-safe base64
    "BLOG_COPILOT_KEK": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
    "GITHUB_CLIENT_ID": "test-gh-id",
    "GITHUB_CLIENT_SECRET": "test-gh-secret",
    "GITHUB_OAUTH_REDIRECT_URI": "http://localhost:8000/auth/github/callback",
    "NOTION_CLIENT_ID": "test-notion-id",
    "NOTION_CLIENT_SECRET": "test-notion-secret",
    "NOTION_OAUTH_REDIRECT_URI": "http://localhost:8000/auth/notion/callback",
    "LINKEDIN_CLIENT_ID": "test-li-id",
    "LINKEDIN_CLIENT_SECRET": "test-li-secret",
    "LINKEDIN_OAUTH_REDIRECT_URI": "http://localhost:8000/auth/linkedin/callback",
    "APP_SECRET_KEY": "test-secret-key-32-chars-minimum-xx",
    "APP_BASE_URL": "http://localhost:8000",
}


@pytest.fixture()
def client() -> TestClient:
    """FastAPI TestClient with dependency-overridden settings.

    Use this fixture in any test that hits a FastAPI endpoint.
    It avoids the need for a real .env file — suitable for CI.
    """
    from app.config import Settings, get_settings

    with patch.dict(os.environ, TEST_ENV, clear=True):
        get_settings.cache_clear()
        from app.api.main import app

        test_settings = Settings()  # type: ignore[call-arg]
        app.dependency_overrides[get_settings] = lambda: test_settings
        yield TestClient(app, raise_server_exceptions=False)
        app.dependency_overrides.clear()
        get_settings.cache_clear()
