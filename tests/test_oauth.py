"""
TDD tests for app/auth/providers.py and app/auth/oauth.py.

Write these BEFORE the implementation (RED phase).
Tests cover: provider config shape, state generation, CSRF validation,
authorization URL construction, and code exchange.
"""

import re

import pytest

# ---------------------------------------------------------------------------
# Helpers / shared fixtures
# ---------------------------------------------------------------------------


def _make_settings(**overrides):
    """Return a minimal mock Settings object."""
    from unittest.mock import MagicMock

    s = MagicMock()
    s.github_client_id = "gh_client_id"
    s.github_client_secret = MagicMock()
    s.github_client_secret.get_secret_value.return_value = "gh_client_secret"
    s.github_oauth_redirect_uri = "https://app.example.com/auth/github/callback"
    s.notion_client_id = "notion_client_id"
    s.notion_client_secret = MagicMock()
    s.notion_client_secret.get_secret_value.return_value = "notion_client_secret"
    s.notion_oauth_redirect_uri = "https://app.example.com/auth/notion/callback"
    s.linkedin_client_id = "linkedin_client_id"
    s.linkedin_client_secret = MagicMock()
    s.linkedin_client_secret.get_secret_value.return_value = "linkedin_client_secret"
    s.linkedin_oauth_redirect_uri = "https://app.example.com/auth/linkedin/callback"
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


# ---------------------------------------------------------------------------
# Provider config — app/auth/providers.py
# ---------------------------------------------------------------------------


class TestProviderConfig:
    def test_github_provider_has_required_fields(self) -> None:
        from app.auth.providers import PROVIDERS, ProviderConfig

        cfg: ProviderConfig = PROVIDERS["github"]
        assert cfg.name == "github"
        assert cfg.auth_url.startswith("https://")
        assert cfg.token_url.startswith("https://")
        assert isinstance(cfg.scopes, list)
        assert len(cfg.scopes) > 0

    def test_notion_provider_has_required_fields(self) -> None:
        from app.auth.providers import PROVIDERS, ProviderConfig

        cfg: ProviderConfig = PROVIDERS["notion"]
        assert cfg.name == "notion"
        assert cfg.auth_url.startswith("https://")
        assert cfg.token_url.startswith("https://")
        assert isinstance(cfg.scopes, list)

    def test_providers_dict_contains_exactly_supported_keys(self) -> None:
        from app.auth.providers import PROVIDERS

        assert set(PROVIDERS.keys()) == {"github", "notion", "linkedin"}

    def test_linkedin_provider_has_required_fields(self) -> None:
        from app.auth.providers import PROVIDERS, ProviderConfig

        cfg: ProviderConfig = PROVIDERS["linkedin"]
        assert cfg.name == "linkedin"
        assert cfg.auth_url.startswith("https://")
        assert "linkedin.com" in cfg.auth_url
        assert cfg.token_url.startswith("https://")
        assert "linkedin.com" in cfg.token_url
        assert isinstance(cfg.scopes, list)
        assert len(cfg.scopes) > 0

    def test_linkedin_scopes_include_social_posting(self) -> None:
        from app.auth.providers import PROVIDERS

        scopes = PROVIDERS["linkedin"].scopes
        scope_str = " ".join(scopes)
        assert "w_member_social" in scope_str

    def test_provider_config_is_immutable(self) -> None:
        """ProviderConfig must be a frozen dataclass."""
        from app.auth.providers import PROVIDERS

        cfg = PROVIDERS["github"]
        with pytest.raises((AttributeError, TypeError)):
            cfg.name = "hacked"  # type: ignore[misc]

    def test_github_scopes_include_repo_read(self) -> None:
        from app.auth.providers import PROVIDERS

        scopes = PROVIDERS["github"].scopes
        # At minimum: read:user + repo (or more specific)
        scope_str = " ".join(scopes)
        assert "repo" in scope_str or "read" in scope_str


# ---------------------------------------------------------------------------
# State generation — app/auth/oauth.py
# ---------------------------------------------------------------------------


class TestStateGeneration:
    def test_generate_state_returns_string(self) -> None:
        from app.auth.oauth import generate_state

        state = generate_state()
        assert isinstance(state, str)

    def test_generate_state_has_minimum_length(self) -> None:
        from app.auth.oauth import generate_state

        state = generate_state()
        assert len(state) >= 32

    def test_generate_state_is_url_safe(self) -> None:
        from app.auth.oauth import generate_state

        state = generate_state()
        # URL-safe base64 or hex — no +, /, = that would break query strings
        assert re.match(r"^[A-Za-z0-9_\-]+$", state), f"state not URL-safe: {state!r}"

    def test_generate_state_is_unique(self) -> None:
        from app.auth.oauth import generate_state

        states = {generate_state() for _ in range(20)}
        assert len(states) == 20


# ---------------------------------------------------------------------------
# CSRF state validation — app/auth/oauth.py
# ---------------------------------------------------------------------------


class TestStateValidation:
    def test_validate_state_passes_on_match(self) -> None:
        from app.auth.oauth import validate_state

        validate_state(expected="abc123", actual="abc123")  # no exception

    def test_validate_state_raises_on_mismatch(self) -> None:
        from app.auth.oauth import OAuthStateError, validate_state

        with pytest.raises(OAuthStateError):
            validate_state(expected="correct", actual="tampered")

    def test_validate_state_raises_on_empty_actual(self) -> None:
        from app.auth.oauth import OAuthStateError, validate_state

        with pytest.raises(OAuthStateError):
            validate_state(expected="abc123", actual="")

    def test_validate_state_raises_on_empty_expected(self) -> None:
        from app.auth.oauth import OAuthStateError, validate_state

        with pytest.raises(OAuthStateError):
            validate_state(expected="", actual="abc123")


# ---------------------------------------------------------------------------
# Authorization URL construction — app/auth/oauth.py
# ---------------------------------------------------------------------------


class TestAuthorizationUrl:
    def test_build_authorization_url_contains_client_id(self) -> None:
        from app.auth.oauth import build_authorization_url

        settings = _make_settings()
        url = build_authorization_url("github", state="teststate", settings=settings)
        assert "gh_client_id" in url

    def test_build_authorization_url_contains_state(self) -> None:
        from app.auth.oauth import build_authorization_url

        settings = _make_settings()
        url = build_authorization_url("github", state="mystate123", settings=settings)
        assert "mystate123" in url

    def test_build_authorization_url_contains_redirect_uri(self) -> None:
        from app.auth.oauth import build_authorization_url

        settings = _make_settings()
        url = build_authorization_url("github", state="s", settings=settings)
        assert "app.example.com" in url

    def test_build_authorization_url_starts_with_provider_auth_url(self) -> None:
        from app.auth.oauth import build_authorization_url
        from app.auth.providers import PROVIDERS

        settings = _make_settings()
        url = build_authorization_url("github", state="s", settings=settings)
        assert url.startswith(PROVIDERS["github"].auth_url)

    def test_build_authorization_url_notion(self) -> None:
        from app.auth.oauth import build_authorization_url
        from app.auth.providers import PROVIDERS

        settings = _make_settings()
        url = build_authorization_url("notion", state="s", settings=settings)
        assert url.startswith(PROVIDERS["notion"].auth_url)

    def test_build_authorization_url_linkedin(self) -> None:
        from app.auth.oauth import build_authorization_url
        from app.auth.providers import PROVIDERS

        settings = _make_settings()
        url = build_authorization_url("linkedin", state="s", settings=settings)
        assert url.startswith(PROVIDERS["linkedin"].auth_url)

    def test_build_authorization_url_linkedin_contains_client_id(self) -> None:
        from app.auth.oauth import build_authorization_url

        settings = _make_settings()
        url = build_authorization_url("linkedin", state="teststate", settings=settings)
        assert "linkedin_client_id" in url

    def test_build_authorization_url_linkedin_contains_social_scope(self) -> None:
        from app.auth.oauth import build_authorization_url

        settings = _make_settings()
        url = build_authorization_url("linkedin", state="s", settings=settings)
        assert "w_member_social" in url

    def test_build_authorization_url_unknown_provider_raises(self) -> None:
        from app.auth.oauth import build_authorization_url

        settings = _make_settings()
        with pytest.raises((KeyError, ValueError)):
            build_authorization_url("twitter", state="s", settings=settings)


# ---------------------------------------------------------------------------
# Code exchange — app/auth/oauth.py
# ---------------------------------------------------------------------------


class TestCodeExchange:
    @pytest.mark.asyncio
    async def test_exchange_code_returns_token_response(self, httpx_mock) -> None:
        """exchange_code posts to token URL and returns parsed TokenResponse."""
        from app.auth.oauth import TokenResponse, exchange_code

        httpx_mock.add_response(
            method="POST",
            json={
                "access_token": "gho_fakeaccesstoken",
                "token_type": "bearer",
                "scope": "repo,read:user",
            },
        )

        settings = _make_settings()
        result = await exchange_code("github", code="authcode123", settings=settings)

        assert isinstance(result, TokenResponse)
        assert result.access_token == "gho_fakeaccesstoken"
        assert result.token_type == "bearer"

    @pytest.mark.asyncio
    async def test_exchange_code_sends_client_credentials(self, httpx_mock) -> None:
        """exchange_code must include client_id, client_secret, code, redirect_uri."""
        import httpx

        from app.auth.oauth import exchange_code

        captured: list[httpx.Request] = []

        def capture(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            return httpx.Response(
                200,
                json={"access_token": "tok", "token_type": "bearer"},
            )

        httpx_mock.add_callback(capture)

        settings = _make_settings()
        await exchange_code("github", code="mycode", settings=settings)

        assert len(captured) == 1
        body = captured[0].content.decode()
        assert "mycode" in body
        assert "gh_client_id" in body

    @pytest.mark.asyncio
    async def test_exchange_code_raises_on_error_response(self, httpx_mock) -> None:
        from app.auth.oauth import OAuthError, exchange_code

        httpx_mock.add_response(
            method="POST",
            json={"error": "bad_verification_code", "error_description": "bad code"},
        )

        settings = _make_settings()
        with pytest.raises(OAuthError):
            await exchange_code("github", code="badcode", settings=settings)

    @pytest.mark.asyncio
    async def test_exchange_code_raises_on_http_error(self, httpx_mock) -> None:
        from app.auth.oauth import OAuthError, exchange_code

        httpx_mock.add_response(status_code=500)

        settings = _make_settings()
        with pytest.raises(OAuthError):
            await exchange_code("github", code="code", settings=settings)


# ---------------------------------------------------------------------------
# TokenResponse shape — app/auth/oauth.py
# ---------------------------------------------------------------------------


class TestTokenResponse:
    def test_token_response_is_immutable(self) -> None:
        from app.auth.oauth import TokenResponse

        tr = TokenResponse(
            access_token="tok",
            token_type="bearer",
            refresh_token=None,
            expires_in=None,
            scope=None,
        )
        with pytest.raises((AttributeError, TypeError)):
            tr.access_token = "hacked"  # type: ignore[misc]

    def test_token_response_optional_fields_default_none(self) -> None:
        from app.auth.oauth import TokenResponse

        tr = TokenResponse(access_token="tok", token_type="bearer")
        assert tr.refresh_token is None
        assert tr.expires_in is None
        assert tr.scope is None
