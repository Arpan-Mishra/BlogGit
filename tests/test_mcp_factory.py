"""
TDD tests for app/tools/mcp_factory.py — get_live_token and build_github_tools.

RED phase: written before the implementation exists.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_repo(*, token_row=None, empty=False):
    """Return a mock OAuthConnectionRepository."""
    repo = MagicMock()
    if empty:
        repo.get.return_value = None
    else:
        conn = MagicMock()
        conn.access_token_encrypted = b"encrypted_token"
        repo.get.return_value = token_row or conn
    return repo


# ---------------------------------------------------------------------------
# get_live_token
# ---------------------------------------------------------------------------


class TestGetLiveToken:
    def test_returns_decrypted_token_when_found(self) -> None:
        from app.tools.mcp_factory import get_live_token

        repo = _make_repo()
        repo.get.return_value.access_token_encrypted = b"some_ciphertext"

        with patch("app.tools.mcp_factory.decrypt_token", return_value="plain_token") as mock_decrypt:
            result = get_live_token(
                repo=repo,
                user_id="user-1",
                provider="github",
                kek="test_kek",
            )

        assert result == "plain_token"
        mock_decrypt.assert_called_once_with(b"some_ciphertext", "test_kek")

    def test_raises_token_not_found_error_when_missing(self) -> None:
        from app.tools.mcp_factory import TokenNotFoundError, get_live_token

        repo = _make_repo(empty=True)

        with pytest.raises(TokenNotFoundError, match="github"):
            get_live_token(
                repo=repo,
                user_id="user-1",
                provider="github",
                kek="test_kek",
            )

    def test_calls_repo_get_with_correct_args(self) -> None:
        from app.tools.mcp_factory import get_live_token

        repo = _make_repo()

        with patch("app.tools.mcp_factory.decrypt_token", return_value="token"):
            get_live_token(repo=repo, user_id="user-42", provider="notion", kek="kek")

        repo.get.assert_called_once_with(user_id="user-42", provider="notion")


# ---------------------------------------------------------------------------
# TokenNotFoundError
# ---------------------------------------------------------------------------


class TestTokenNotFoundError:
    def test_is_exception(self) -> None:
        from app.tools.mcp_factory import TokenNotFoundError

        assert issubclass(TokenNotFoundError, Exception)

    def test_message_contains_provider(self) -> None:
        from app.tools.mcp_factory import TokenNotFoundError

        err = TokenNotFoundError("linkedin")
        assert "linkedin" in str(err)


# ---------------------------------------------------------------------------
# build_github_tools
# ---------------------------------------------------------------------------


class TestBuildGithubTools:
    def test_returns_list_of_tools(self) -> None:
        from app.tools.mcp_factory import build_github_tools

        tools = build_github_tools(github_token="ghp_test_token")
        assert isinstance(tools, list)
        assert len(tools) > 0

    def test_tools_have_name_and_description(self) -> None:
        from app.tools.mcp_factory import build_github_tools

        tools = build_github_tools(github_token="ghp_test_token")
        for tool in tools:
            assert hasattr(tool, "name")
            assert hasattr(tool, "description")
            assert tool.name
            assert tool.description

    def test_tools_include_readme_reader(self) -> None:
        from app.tools.mcp_factory import build_github_tools

        tools = build_github_tools(github_token="ghp_test_token")
        names = [t.name for t in tools]
        assert any("readme" in name.lower() for name in names)

    def test_tools_include_file_tree(self) -> None:
        from app.tools.mcp_factory import build_github_tools

        tools = build_github_tools(github_token="ghp_test_token")
        names = [t.name for t in tools]
        assert any("tree" in name.lower() or "files" in name.lower() for name in names)
