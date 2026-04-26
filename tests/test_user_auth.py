"""
Tests for app/api/routes/user_auth.py and app/api/dependencies.py.

Covers signup, login, logout, connections, and JWT validation dependencies.
"""

import os
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from supabase_auth.errors import AuthApiError

from tests.conftest import TEST_ENV


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_user(user_id: str = "user-123", email: str = "test@example.com"):
    user = MagicMock()
    user.id = user_id
    user.email = email
    return user


def _make_mock_session(
    access_token: str = "access-tok",
    refresh_token: str = "refresh-tok",
):
    session = MagicMock()
    session.access_token = access_token
    session.refresh_token = refresh_token
    return session


def _make_auth_result(user_id: str = "user-123", email: str = "test@example.com"):
    result = MagicMock()
    result.user = _make_mock_user(user_id, email)
    result.session = _make_mock_session()
    return result


# ---------------------------------------------------------------------------
# Signup
# ---------------------------------------------------------------------------


class TestSignup:
    @patch("app.api.routes.user_auth.create_client")
    def test_signup_success(self, mock_create_client, client: TestClient) -> None:
        mock_supabase = MagicMock()
        mock_supabase.auth.sign_up.return_value = _make_auth_result(
            email="new@example.com"
        )
        mock_create_client.return_value = mock_supabase

        resp = client.post(
            "/user/signup",
            json={"email": "new@example.com", "password": "securepass123"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["access_token"] == "access-tok"
        assert data["refresh_token"] == "refresh-tok"
        assert data["user_id"] == "user-123"
        assert data["email"] == "new@example.com"

    def test_signup_short_password_returns_422(self, client: TestClient) -> None:
        resp = client.post(
            "/user/signup",
            json={"email": "new@example.com", "password": "short"},
        )
        assert resp.status_code == 422

    def test_signup_invalid_email_returns_422(self, client: TestClient) -> None:
        resp = client.post(
            "/user/signup",
            json={"email": "not-an-email", "password": "securepass123"},
        )
        assert resp.status_code == 422

    @patch("app.api.routes.user_auth.create_client")
    def test_signup_supabase_error_returns_400(
        self, mock_create_client, client: TestClient
    ) -> None:
        from supabase_auth.errors import AuthApiError

        mock_supabase = MagicMock()
        mock_supabase.auth.sign_up.side_effect = AuthApiError(
            "User already registered", 400, code=None
        )
        mock_create_client.return_value = mock_supabase

        resp = client.post(
            "/user/signup",
            json={"email": "dup@example.com", "password": "securepass123"},
        )
        assert resp.status_code == 400

    @patch("app.api.routes.user_auth.create_client")
    def test_signup_no_session_returns_400(
        self, mock_create_client, client: TestClient
    ) -> None:
        result = MagicMock()
        result.user = _make_mock_user()
        result.session = None
        mock_supabase = MagicMock()
        mock_supabase.auth.sign_up.return_value = result
        mock_create_client.return_value = mock_supabase

        resp = client.post(
            "/user/signup",
            json={"email": "new@example.com", "password": "securepass123"},
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------


class TestLogin:
    @patch("app.api.routes.user_auth.create_client")
    def test_login_success(self, mock_create_client, client: TestClient) -> None:
        mock_supabase = MagicMock()
        mock_supabase.auth.sign_in_with_password.return_value = _make_auth_result()
        mock_create_client.return_value = mock_supabase

        resp = client.post(
            "/user/login",
            json={"email": "test@example.com", "password": "securepass123"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["access_token"] == "access-tok"
        assert data["user_id"] == "user-123"

    @patch("app.api.routes.user_auth.create_client")
    def test_login_wrong_password_returns_401(
        self, mock_create_client, client: TestClient
    ) -> None:
        from supabase_auth.errors import AuthApiError

        mock_supabase = MagicMock()
        mock_supabase.auth.sign_in_with_password.side_effect = AuthApiError(
            "Invalid login credentials", 400, code=None
        )
        mock_create_client.return_value = mock_supabase

        resp = client.post(
            "/user/login",
            json={"email": "test@example.com", "password": "wrongpass"},
        )
        assert resp.status_code == 401

    @patch("app.api.routes.user_auth.create_client")
    def test_login_no_session_returns_401(
        self, mock_create_client, client: TestClient
    ) -> None:
        result = MagicMock()
        result.user = None
        result.session = None
        mock_supabase = MagicMock()
        mock_supabase.auth.sign_in_with_password.return_value = result
        mock_create_client.return_value = mock_supabase

        resp = client.post(
            "/user/login",
            json={"email": "test@example.com", "password": "somepass"},
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------


class TestLogout:
    @patch("app.api.routes.user_auth.create_client")
    def test_logout_with_token(self, mock_create_client, client: TestClient) -> None:
        mock_supabase = MagicMock()
        mock_create_client.return_value = mock_supabase

        resp = client.post(
            "/user/logout",
            headers={"Authorization": "Bearer some-token"},
        )
        assert resp.status_code == 200
        assert resp.json() == {"status": "logged_out"}

    def test_logout_without_token(self, client: TestClient) -> None:
        resp = client.post("/user/logout")
        assert resp.status_code == 200
        assert resp.json() == {"status": "logged_out"}


# ---------------------------------------------------------------------------
# Connections
# ---------------------------------------------------------------------------


class TestConnections:
    @patch("app.api.dependencies.create_client")
    @patch("app.api.routes.user_auth.create_client")
    def test_connections_returns_all_providers(
        self, mock_route_client, mock_dep_client, client: TestClient
    ) -> None:
        mock_user_resp = MagicMock()
        mock_user_resp.user = _make_mock_user()
        mock_supabase_dep = MagicMock()
        mock_supabase_dep.auth.get_user.return_value = mock_user_resp
        mock_dep_client.return_value = mock_supabase_dep

        fake_repo_supabase = MagicMock()
        fake_repo_supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = None
        mock_route_client.return_value = fake_repo_supabase

        resp = client.get(
            "/user/connections",
            headers={"Authorization": "Bearer valid-token"},
        )
        assert resp.status_code == 200
        data = resp.json()
        providers = [c["provider"] for c in data["connections"]]
        assert "github" in providers
        assert "notion" in providers
        assert "linkedin" in providers
        assert "medium" in providers

    @patch("app.api.dependencies.create_client")
    @patch("app.api.routes.user_auth.create_client")
    def test_connections_shows_connected_provider(
        self, mock_route_client, mock_dep_client, client: TestClient
    ) -> None:
        mock_user_resp = MagicMock()
        mock_user_resp.user = _make_mock_user()
        mock_supabase_dep = MagicMock()
        mock_supabase_dep.auth.get_user.return_value = mock_user_resp
        mock_dep_client.return_value = mock_supabase_dep

        def _fake_get(user_id: str, provider: str):
            if provider == "github":
                return MagicMock()
            return None

        fake_repo_supabase = MagicMock()
        mock_route_client.return_value = fake_repo_supabase

        from app.api.routes.user_auth import _get_oauth_repo, get_connections
        from app.db.repositories import SupabaseOAuthConnectionRepository
        from app.api.main import app

        fake_repo = MagicMock(spec=SupabaseOAuthConnectionRepository)
        fake_repo.get.side_effect = _fake_get
        app.dependency_overrides[_get_oauth_repo] = lambda: fake_repo

        resp = client.get(
            "/user/connections",
            headers={"Authorization": "Bearer valid-token"},
        )

        app.dependency_overrides.pop(_get_oauth_repo, None)

        assert resp.status_code == 200
        connections = {
            c["provider"]: c["connected"] for c in resp.json()["connections"]
        }
        assert connections["github"] is True
        assert connections["notion"] is False

    def test_connections_without_auth_returns_401(self, client: TestClient) -> None:
        resp = client.get("/user/connections")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# JWT validation dependencies
# ---------------------------------------------------------------------------


class TestGetCurrentUser:
    @patch("app.api.dependencies.create_client")
    def test_valid_token_returns_user_id(self, mock_create_client) -> None:
        import asyncio
        from app.api.dependencies import get_current_user
        from app.config import Settings

        mock_user_resp = MagicMock()
        mock_user_resp.user = _make_mock_user("uid-abc")
        mock_supabase = MagicMock()
        mock_supabase.auth.get_user.return_value = mock_user_resp
        mock_create_client.return_value = mock_supabase

        request = MagicMock()
        request.headers.get.return_value = "Bearer good-token"

        with patch.dict(os.environ, TEST_ENV, clear=True):
            from app.config import get_settings
            get_settings.cache_clear()
            settings = Settings()  # type: ignore[call-arg]
            user_id = asyncio.get_event_loop().run_until_complete(
                get_current_user(request, settings)
            )
            get_settings.cache_clear()

        assert user_id == "uid-abc"

    def test_missing_token_raises_401(self) -> None:
        import asyncio
        from fastapi import HTTPException
        from app.api.dependencies import get_current_user
        from app.config import Settings

        request = MagicMock()
        request.headers.get.return_value = ""

        with patch.dict(os.environ, TEST_ENV, clear=True):
            from app.config import get_settings
            get_settings.cache_clear()
            settings = Settings()  # type: ignore[call-arg]
            with pytest.raises(HTTPException) as exc_info:
                asyncio.get_event_loop().run_until_complete(
                    get_current_user(request, settings)
                )
            get_settings.cache_clear()

        assert exc_info.value.status_code == 401


class TestGetOptionalUser:
    @patch("app.api.dependencies.create_client")
    def test_valid_token_returns_user_id(self, mock_create_client) -> None:
        import asyncio
        from app.api.dependencies import get_optional_user
        from app.config import Settings

        mock_user_resp = MagicMock()
        mock_user_resp.user = _make_mock_user("uid-xyz")
        mock_supabase = MagicMock()
        mock_supabase.auth.get_user.return_value = mock_user_resp
        mock_create_client.return_value = mock_supabase

        request = MagicMock()
        request.headers.get.return_value = "Bearer good-token"

        with patch.dict(os.environ, TEST_ENV, clear=True):
            from app.config import get_settings
            get_settings.cache_clear()
            settings = Settings()  # type: ignore[call-arg]
            user_id = asyncio.get_event_loop().run_until_complete(
                get_optional_user(request, settings)
            )
            get_settings.cache_clear()

        assert user_id == "uid-xyz"

    def test_no_token_returns_anonymous(self) -> None:
        import asyncio
        from app.api.dependencies import get_optional_user
        from app.config import Settings

        request = MagicMock()
        request.headers.get.return_value = ""

        with patch.dict(os.environ, TEST_ENV, clear=True):
            from app.config import get_settings
            get_settings.cache_clear()
            settings = Settings()  # type: ignore[call-arg]
            user_id = asyncio.get_event_loop().run_until_complete(
                get_optional_user(request, settings)
            )
            get_settings.cache_clear()

        assert user_id == "anonymous"

    @patch("app.api.dependencies.create_client")
    def test_invalid_token_returns_anonymous(self, mock_create_client) -> None:
        import asyncio
        from app.api.dependencies import get_optional_user
        from app.config import Settings

        mock_supabase = MagicMock()
        mock_supabase.auth.get_user.side_effect = AuthApiError("invalid", 401, code=None)
        mock_create_client.return_value = mock_supabase

        request = MagicMock()
        request.headers.get.return_value = "Bearer bad-token"

        with patch.dict(os.environ, TEST_ENV, clear=True):
            from app.config import get_settings
            get_settings.cache_clear()
            settings = Settings()  # type: ignore[call-arg]
            user_id = asyncio.get_event_loop().run_until_complete(
                get_optional_user(request, settings)
            )
            get_settings.cache_clear()

        assert user_id == "anonymous"
