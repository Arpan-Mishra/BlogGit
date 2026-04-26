"""
TDD tests for FastAPI auth routes:
  GET  /auth/{provider}/start     — redirect to provider OAuth page
  GET  /auth/{provider}/callback  — exchange code, store tokens, redirect to app

RED phase: written before the routes exist.
"""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# Full set of env vars required by Settings
_ENV = {
    "ANTHROPIC_API_KEY": "sk-ant-test",
    "LANGSMITH_API_KEY": "ls-test",
    "SUPABASE_URL": "https://test.supabase.co",
    "SUPABASE_ANON_KEY": "test-anon-key",
    "SUPABASE_SERVICE_ROLE_KEY": "test-service-key",
    "BLOG_COPILOT_KEK": "dGVzdC1rZXktMzItY2hhcnMtZm9yLWZlcm5ldC10ZXN0",
    "GITHUB_CLIENT_ID": "test-gh-id",
    "GITHUB_CLIENT_SECRET": "test-gh-secret",
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


# ---------------------------------------------------------------------------
# App fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def client():
    from app.config import get_settings

    with patch.dict(os.environ, _ENV, clear=True):
        get_settings.cache_clear()
        from app.api.main import app

        # Override the dependency so it uses our test env
        app.dependency_overrides = {}
        yield TestClient(app, follow_redirects=False)
        get_settings.cache_clear()


# ---------------------------------------------------------------------------
# /auth/{provider}/start
# ---------------------------------------------------------------------------


class TestAuthStart:
    def test_start_github_redirects(self, client: TestClient) -> None:
        response = client.get("/auth/github/start")
        assert response.status_code == 302

    def test_start_github_location_contains_github_domain(self, client: TestClient) -> None:
        response = client.get("/auth/github/start")
        location = response.headers["location"]
        assert "github.com" in location

    def test_start_github_location_contains_client_id(self, client: TestClient) -> None:
        response = client.get("/auth/github/start")
        location = response.headers["location"]
        assert "client_id" in location

    def test_start_github_location_contains_state(self, client: TestClient) -> None:
        response = client.get("/auth/github/start")
        location = response.headers["location"]
        assert "state=" in location

    def test_start_sets_state_cookie(self, client: TestClient) -> None:
        response = client.get("/auth/github/start")
        assert "oauth_state" in response.cookies

    def test_start_notion_redirects(self, client: TestClient) -> None:
        response = client.get("/auth/notion/start")
        assert response.status_code == 302

    def test_start_notion_location_contains_notion_domain(self, client: TestClient) -> None:
        response = client.get("/auth/notion/start")
        location = response.headers["location"]
        assert "notion.com" in location

    def test_start_unknown_provider_returns_404(self, client: TestClient) -> None:
        response = client.get("/auth/twitter/start")
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# /auth/{provider}/callback
# ---------------------------------------------------------------------------


class TestAuthCallback:
    def test_callback_without_state_cookie_returns_400(self, client: TestClient) -> None:
        # No cookie set — CSRF check should fail
        response = client.get(
            "/auth/github/callback", params={"code": "mycode", "state": "somestate"}
        )
        assert response.status_code == 400

    def test_callback_state_mismatch_returns_400(self, client: TestClient) -> None:
        # Set cookie to one value, send different state in query param
        client.cookies.set("oauth_state", "correct_state")
        response = client.get(
            "/auth/github/callback",
            params={"code": "mycode", "state": "wrong_state"},
        )
        assert response.status_code == 400

    def test_callback_missing_code_returns_422(self, client: TestClient) -> None:
        client.cookies.set("oauth_state", "state123")
        response = client.get("/auth/github/callback", params={"state": "state123"})
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_callback_valid_redirects_to_app(self) -> None:
        """Happy path: correct state, exchange returns tokens, redirect to /."""
        from cryptography.fernet import Fernet
        from httpx import ASGITransport, AsyncClient

        from app.config import get_settings

        fake_repo = MagicMock()
        fake_repo.upsert = MagicMock()
        valid_kek = Fernet.generate_key().decode()

        with patch.dict(os.environ, _ENV, clear=True):
            get_settings.cache_clear()
            from app.api.main import app
            from app.api.routes.auth import get_kek, get_oauth_repo

            # dependency_overrides is the reliable way to replace FastAPI deps
            app.dependency_overrides[get_kek] = lambda: valid_kek
            app.dependency_overrides[get_oauth_repo] = lambda: fake_repo

            with patch(
                "app.api.routes.auth.exchange_code",
                new=AsyncMock(
                    return_value=MagicMock(
                        access_token="gho_faketoken",
                        token_type="bearer",
                        refresh_token=None,
                        expires_in=None,
                        scope="repo",
                    )
                ),
            ):
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as ac:
                    start_resp = await ac.get("/auth/github/start", follow_redirects=False)
                    state_cookie = start_resp.cookies.get("oauth_state")
                    assert state_cookie is not None

                    callback_resp = await ac.get(
                        "/auth/github/callback",
                        params={"code": "authcode", "state": state_cookie},
                        follow_redirects=False,
                    )
                    assert callback_resp.status_code == 302
                    assert callback_resp.headers["location"] == "http://localhost:8501?connected=github"

            app.dependency_overrides.clear()
            get_settings.cache_clear()

    def test_callback_provider_error_returns_400(self, client: TestClient) -> None:
        """Provider returns error param (user denied OAuth)."""
        client.cookies.set("oauth_state", "state123")
        response = client.get(
            "/auth/github/callback",
            params={"error": "access_denied", "state": "state123"},
        )
        assert response.status_code == 400


# ---------------------------------------------------------------------------
# /auth/linkedin/start
# ---------------------------------------------------------------------------


class TestLinkedInStart:
    def test_start_linkedin_redirects(self, client: TestClient) -> None:
        response = client.get("/auth/linkedin/start")
        assert response.status_code == 302

    def test_start_linkedin_location_contains_linkedin_domain(self, client: TestClient) -> None:
        response = client.get("/auth/linkedin/start")
        location = response.headers["location"]
        assert "linkedin.com" in location

    def test_start_linkedin_location_contains_social_scope(self, client: TestClient) -> None:
        response = client.get("/auth/linkedin/start")
        location = response.headers["location"]
        assert "w_member_social" in location

    def test_start_linkedin_sets_state_cookie(self, client: TestClient) -> None:
        response = client.get("/auth/linkedin/start")
        assert "oauth_state" in response.cookies


# ---------------------------------------------------------------------------
# POST /auth/medium/token
# ---------------------------------------------------------------------------


class TestMediumToken:
    def test_medium_token_missing_body_returns_422(self, client: TestClient) -> None:
        response = client.post("/auth/medium/token")
        assert response.status_code == 422

    def test_medium_token_empty_token_returns_422(self, client: TestClient) -> None:
        response = client.post("/auth/medium/token", json={"token": ""})
        assert response.status_code == 422

    def test_medium_token_valid_stores_and_returns_200(self, client: TestClient) -> None:
        """Happy path: Medium API validates token, it is stored encrypted."""
        from unittest.mock import AsyncMock, MagicMock, patch

        from cryptography.fernet import Fernet

        from app.api.main import app
        from app.api.routes.auth import get_kek, get_oauth_repo

        fake_repo = MagicMock()
        fake_repo.upsert = MagicMock()
        valid_kek = Fernet.generate_key().decode()

        app.dependency_overrides[get_kek] = lambda: valid_kek
        app.dependency_overrides[get_oauth_repo] = lambda: fake_repo
        try:
            with patch(
                "app.api.routes.auth.validate_medium_token",
                new=AsyncMock(return_value={"id": "medium-user-id", "username": "testuser"}),
            ):
                response = client.post(
                    "/auth/medium/token",
                    json={"token": "fake-medium-token"},
                    headers={"x-user-id": "user-123"},
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        assert response.json()["status"] == "connected"

    def test_medium_token_invalid_returns_400(self, client: TestClient) -> None:
        """If Medium API rejects the token, return 400."""
        from unittest.mock import AsyncMock, patch

        from app.api.routes.auth import MediumTokenError

        with patch(
            "app.api.routes.auth.validate_medium_token",
            new=AsyncMock(side_effect=MediumTokenError("invalid token")),
        ):
            response = client.post(
                "/auth/medium/token",
                json={"token": "bad-token"},
            )
        assert response.status_code == 400


# ---------------------------------------------------------------------------
# GET /auth/oauth-success
# ---------------------------------------------------------------------------


class TestOAuthSuccess:
    def test_oauth_success_returns_html(self, client: TestClient) -> None:
        response = client.get("/auth/oauth-success")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_oauth_success_contains_auto_close(self, client: TestClient) -> None:
        response = client.get("/auth/oauth-success")
        assert "window.close()" in response.text

    def test_oauth_success_contains_connected_message(self, client: TestClient) -> None:
        response = client.get("/auth/oauth-success")
        assert "Connected!" in response.text


# ---------------------------------------------------------------------------
# GET /auth/{provider}/status
# ---------------------------------------------------------------------------


class TestAuthStatus:
    def test_status_returns_false_for_unknown_user(self, client: TestClient) -> None:
        from app.api.dependencies import get_optional_user
        from app.api.routes.auth import get_oauth_repo
        from app.api.main import app

        fake_repo = MagicMock()
        fake_repo.get = MagicMock(return_value=None)

        app.dependency_overrides[get_oauth_repo] = lambda: fake_repo
        app.dependency_overrides[get_optional_user] = lambda: "unknown-user"
        try:
            response = client.get("/auth/linkedin/status")
        finally:
            app.dependency_overrides.pop(get_oauth_repo, None)
            app.dependency_overrides.pop(get_optional_user, None)

        assert response.status_code == 200
        assert response.json() == {"connected": False}
        fake_repo.get.assert_called_once_with(user_id="unknown-user", provider="linkedin")

    def test_status_returns_true_for_connected_user(self, client: TestClient) -> None:
        from app.api.dependencies import get_optional_user
        from app.api.routes.auth import get_oauth_repo
        from app.api.main import app

        fake_repo = MagicMock()
        fake_repo.get = MagicMock(return_value=MagicMock())

        app.dependency_overrides[get_oauth_repo] = lambda: fake_repo
        app.dependency_overrides[get_optional_user] = lambda: "connected-user"
        try:
            response = client.get("/auth/linkedin/status")
        finally:
            app.dependency_overrides.pop(get_oauth_repo, None)
            app.dependency_overrides.pop(get_optional_user, None)

        assert response.status_code == 200
        assert response.json() == {"connected": True}

    def test_status_defaults_to_anonymous_user(self, client: TestClient) -> None:
        from app.api.dependencies import get_optional_user
        from app.api.routes.auth import get_oauth_repo
        from app.api.main import app

        fake_repo = MagicMock()
        fake_repo.get = MagicMock(return_value=None)

        app.dependency_overrides[get_oauth_repo] = lambda: fake_repo
        app.dependency_overrides[get_optional_user] = lambda: "anonymous"
        try:
            response = client.get("/auth/linkedin/status")
        finally:
            app.dependency_overrides.pop(get_oauth_repo, None)
            app.dependency_overrides.pop(get_optional_user, None)

        assert response.status_code == 200
        fake_repo.get.assert_called_once_with(user_id="anonymous", provider="linkedin")


# ---------------------------------------------------------------------------
# Popup mode: /auth/{provider}/start?popup=true
# ---------------------------------------------------------------------------


class TestPopupMode:
    def test_start_with_popup_sets_popup_cookie(self, client: TestClient) -> None:
        response = client.get("/auth/github/start?popup=true")
        assert response.status_code == 302
        assert "oauth_popup" in response.cookies

    def test_start_without_popup_no_popup_cookie(self, client: TestClient) -> None:
        response = client.get("/auth/github/start")
        assert response.status_code == 302
        assert "oauth_popup" not in response.cookies

    @pytest.mark.asyncio
    async def test_callback_popup_redirects_to_success_page(self) -> None:
        """With popup cookie set, callback redirects to /auth/oauth-success."""
        from cryptography.fernet import Fernet
        from httpx import ASGITransport, AsyncClient

        from app.config import get_settings

        fake_repo = MagicMock()
        fake_repo.upsert = MagicMock()
        valid_kek = Fernet.generate_key().decode()

        with patch.dict(os.environ, _ENV, clear=True):
            get_settings.cache_clear()
            from app.api.main import app
            from app.api.routes.auth import get_kek, get_oauth_repo

            app.dependency_overrides[get_kek] = lambda: valid_kek
            app.dependency_overrides[get_oauth_repo] = lambda: fake_repo

            with patch(
                "app.api.routes.auth.exchange_code",
                new=AsyncMock(
                    return_value=MagicMock(
                        access_token="gho_faketoken",
                        token_type="bearer",
                        refresh_token=None,
                        expires_in=None,
                        scope="repo",
                    )
                ),
            ):
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as ac:
                    start_resp = await ac.get(
                        "/auth/github/start?popup=true", follow_redirects=False
                    )
                    state_cookie = start_resp.cookies.get("oauth_state")
                    assert state_cookie is not None

                    callback_resp = await ac.get(
                        "/auth/github/callback",
                        params={"code": "authcode", "state": state_cookie},
                        follow_redirects=False,
                    )
                    assert callback_resp.status_code == 302
                    location = callback_resp.headers["location"]
                    assert "/auth/oauth-success" in location
                    assert "connected=github" not in location

            app.dependency_overrides.clear()
            get_settings.cache_clear()
