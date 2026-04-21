"""
AmplifyrMCP client wrapper for LinkedIn and Medium publishing tools.

AmplifyrMCP (forked from supersaiyane/AmplifyrMCP) is a TypeScript MCP server
that exposes tools for:
  - LinkedIn: create-post, publish-article, get-profile, etc.
  - Medium: medium-publish, get-medium-user, etc.

The server runs as a stdio subprocess. We bypass its built-in SQLite token
storage by setting TOKEN_STORE_TYPE=env and injecting tokens via env vars.

The TypeScript server must be built first:
    cd mcp-servers/amplifyr && npm install && npm run build

Usage:
    client = build_amplifyr_client(
        linkedin_token="...",
        medium_token="...",
        server_path="mcp-servers/amplifyr",
    )
    # client is a MultiServerMCPClient (langchain-mcp-adapters)
    # tools = await client.get_tools()
"""

import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_SERVER_PATH = Path(__file__).parent.parent.parent / "mcp-servers" / "amplifyr"


def build_amplifyr_client(
    linkedin_token: str | None = None,
    medium_token: str | None = None,
    server_path: str | Path | None = None,
) -> Any:
    """Build a MultiServerMCPClient for the AmplifyrMCP server.

    Parameters
    ----------
    linkedin_token:
        Decrypted LinkedIn OAuth access token. Pass None if not connected;
        LinkedIn tools will be unavailable but the client still starts.
    medium_token:
        Decrypted Medium integration token. Pass None if not connected.
    server_path:
        Path to the AmplifyrMCP server directory containing ``dist/index.js``.
        Defaults to ``mcp-servers/amplifyr`` relative to the project root.

    Returns
    -------
    MultiServerMCPClient instance (langchain-mcp-adapters). The caller must
    use ``await client.get_tools()`` to retrieve available tools. The client
    is NOT an async context manager — do not use ``async with``.
    """
    from langchain_mcp_adapters.client import MultiServerMCPClient  # type: ignore[import]

    resolved_path = Path(server_path) if server_path is not None else _DEFAULT_SERVER_PATH
    dist_js = resolved_path / "dist" / "index.js"

    if not dist_js.exists():
        raise FileNotFoundError(
            f"AmplifyrMCP dist not found at {dist_js}. "
            "Run: cd mcp-servers/amplifyr && npm install && npm run build"
        )

    env: dict[str, str] = {
        **os.environ,
        "TOKEN_STORE_TYPE": "env",
    }
    if linkedin_token:
        env["LINKEDIN_ACCESS_TOKEN"] = linkedin_token
    if medium_token:
        env["MEDIUM_INTEGRATION_TOKEN"] = medium_token

    client = MultiServerMCPClient(
        {
            "amplifyr": {
                "command": "node",
                "args": [str(dist_js)],
                "env": env,
                "transport": "stdio",
            }
        }
    )
    logger.info(
        "AmplifyrMCP client configured (linkedin=%s, medium=%s)",
        "connected" if linkedin_token else "not connected",
        "connected" if medium_token else "not connected",
    )
    return client
