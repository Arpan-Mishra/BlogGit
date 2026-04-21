"""
TDD tests for app/tools/github_mcp.py — GitHub REST API tool wrappers.

We mock httpx.Client so no real network calls are made.
"""

import base64
from unittest.mock import MagicMock, patch

import httpx
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_client(status_code: int = 200, json_data: dict | None = None):
    """Return a context-manager mock for httpx.Client."""
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = json_data or {}
    if status_code >= 400:
        response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=response
        )
    else:
        response.raise_for_status.return_value = None

    client_instance = MagicMock()
    client_instance.get.return_value = response

    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=client_instance)
    ctx.__exit__ = MagicMock(return_value=False)
    return ctx, client_instance


# ---------------------------------------------------------------------------
# get_readme
# ---------------------------------------------------------------------------


class TestGetReadme:
    def test_returns_decoded_content(self) -> None:
        from app.tools.github_mcp import get_readme

        content = "# Hello World\nA sample project."
        encoded = base64.b64encode(content.encode()).decode()
        ctx, _ = _mock_client(json_data={"content": encoded})

        with patch("httpx.Client", return_value=ctx):
            result = get_readme("owner", "repo", token="ghp_test")

        assert result == content

    def test_returns_empty_string_when_404(self) -> None:
        from app.tools.github_mcp import get_readme

        ctx, _ = _mock_client(status_code=404, json_data={})

        with patch("httpx.Client", return_value=ctx):
            result = get_readme("owner", "repo", token="ghp_test")

        assert result == ""

    def test_raises_on_server_error(self) -> None:
        from app.tools.github_mcp import get_readme

        ctx, _ = _mock_client(status_code=500, json_data={})

        with patch("httpx.Client", return_value=ctx):
            with pytest.raises(httpx.HTTPStatusError):
                get_readme("owner", "repo", token="ghp_test")


# ---------------------------------------------------------------------------
# get_file_tree
# ---------------------------------------------------------------------------


class TestGetFileTree:
    def test_returns_file_paths(self) -> None:
        from app.tools.github_mcp import get_file_tree

        repo_data = {"default_branch": "main"}
        tree_data = {
            "tree": [
                {"path": "src/main.py", "type": "blob"},
                {"path": "src/", "type": "tree"},
                {"path": "tests/test_main.py", "type": "blob"},
            ]
        }

        client_instance = MagicMock()
        # First call: get repo metadata; second call: get tree
        client_instance.get.side_effect = [
            MagicMock(
                status_code=200,
                json=MagicMock(return_value=repo_data),
                raise_for_status=MagicMock(),
            ),
            MagicMock(
                status_code=200,
                json=MagicMock(return_value=tree_data),
                raise_for_status=MagicMock(),
            ),
        ]

        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=client_instance)
        ctx.__exit__ = MagicMock(return_value=False)

        with patch("httpx.Client", return_value=ctx):
            result = get_file_tree("owner", "repo", token="ghp_test")

        # Only blob entries should appear (not tree directories)
        lines = result.splitlines()
        assert "src/main.py" in lines
        assert "tests/test_main.py" in lines
        # directory entries (type=tree) should be excluded
        assert "src/" not in lines

    def test_respects_max_entries(self) -> None:
        from app.tools.github_mcp import get_file_tree

        repo_data = {"default_branch": "main"}
        many_files = [{"path": f"file{i}.py", "type": "blob"} for i in range(300)]
        tree_data = {"tree": many_files}

        client_instance = MagicMock()
        client_instance.get.side_effect = [
            MagicMock(
                status_code=200,
                json=MagicMock(return_value=repo_data),
                raise_for_status=MagicMock(),
            ),
            MagicMock(
                status_code=200,
                json=MagicMock(return_value=tree_data),
                raise_for_status=MagicMock(),
            ),
        ]
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=client_instance)
        ctx.__exit__ = MagicMock(return_value=False)

        with patch("httpx.Client", return_value=ctx):
            result = get_file_tree("owner", "repo", token="ghp_test", max_entries=5)

        assert len(result.splitlines()) == 5


# ---------------------------------------------------------------------------
# get_recent_commits
# ---------------------------------------------------------------------------


class TestGetRecentCommits:
    def test_returns_sha_and_message(self) -> None:
        from app.tools.github_mcp import get_recent_commits

        commits = [
            {"sha": "abc1234def", "commit": {"message": "feat: initial commit\n\nBody text"}},
            {"sha": "def5678abc", "commit": {"message": "fix: typo"}},
        ]
        ctx, _ = _mock_client(json_data=commits)

        with patch("httpx.Client", return_value=ctx):
            result = get_recent_commits("owner", "repo", token="ghp_test", n=2)

        lines = result.splitlines()
        assert len(lines) == 2
        assert lines[0].startswith("abc1234")
        assert "feat: initial commit" in lines[0]

    def test_only_first_line_of_message(self) -> None:
        from app.tools.github_mcp import get_recent_commits

        commits = [
            {
                "sha": "aaa0000",
                "commit": {"message": "feat: cool feature\n\nLong description here."},
            }
        ]
        ctx, _ = _mock_client(json_data=commits)

        with patch("httpx.Client", return_value=ctx):
            result = get_recent_commits("owner", "repo", token="ghp_test", n=1)

        assert "\n\n" not in result
        assert "Long description" not in result


# ---------------------------------------------------------------------------
# get_repo_metadata
# ---------------------------------------------------------------------------


class TestGetRepoMetadata:
    def test_includes_language_and_description(self) -> None:
        from app.tools.github_mcp import get_repo_metadata

        repo_data = {
            "language": "Python",
            "description": "A blog copilot.",
            "topics": ["ai", "blog"],
            "stargazers_count": 42,
        }
        ctx, _ = _mock_client(json_data=repo_data)

        with patch("httpx.Client", return_value=ctx):
            result = get_repo_metadata("owner", "repo", token="ghp_test")

        assert "Python" in result
        assert "A blog copilot." in result
        assert "ai" in result
        assert "42" in result

    def test_handles_missing_optional_fields(self) -> None:
        from app.tools.github_mcp import get_repo_metadata

        ctx, _ = _mock_client(json_data={})

        with patch("httpx.Client", return_value=ctx):
            result = get_repo_metadata("owner", "repo", token="ghp_test")

        assert "unknown" in result
