"""
Demo CLI script for the repo_analyzer node.

Usage:
    python scripts/analyze_repo.py <github_repo_url> [--user-id USER_ID]

Example:
    python scripts/analyze_repo.py https://github.com/anthropics/anthropic-sdk-python

Prerequisites:
    - GITHUB_TOKEN or a GitHub OAuth token stored in Supabase oauth_connections
    - All required env vars in .env (see .env.example)

The script runs the repo_analyzer node in isolation with a real GitHub token,
prints the resulting RepoSummary, and traces the run to LangSmith.
"""

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

# Ensure the project root is on sys.path when run from any directory
_PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


async def main(repo_url: str, user_id: str) -> None:
    from app.agent.nodes import make_repo_analyzer_node
    from app.agent.state import BlogState, RepoSummary
    from app.config import get_settings
    from app.tools.mcp_factory import build_github_tools, get_live_token

    settings = get_settings()

    # -- Resolve GitHub token --------------------------------------------------
    # Prefer a raw env var for quick demo usage; fall back to Supabase lookup.
    github_token = os.environ.get("GITHUB_TOKEN")
    if not github_token:
        from supabase import create_client  # type: ignore[import]

        from app.db.repositories import SupabaseOAuthConnectionRepository
        from app.tools.mcp_factory import TokenNotFoundError

        client = create_client(
            settings.supabase_url,
            settings.supabase_service_role_key.get_secret_value(),
        )
        repo = SupabaseOAuthConnectionRepository(client)
        try:
            github_token = get_live_token(
                repo=repo,
                user_id=user_id,
                provider="github",
                kek=settings.blog_copilot_kek.get_secret_value(),
            )
            logger.info("GitHub token loaded from Supabase for user_id=%s", user_id)
        except TokenNotFoundError:
            logger.error(
                "No GitHub token found for user_id=%s. "
                "Set GITHUB_TOKEN env var or connect GitHub via the web app.",
                user_id,
            )
            sys.exit(1)

    # -- Build tools and LLM ---------------------------------------------------
    tools = build_github_tools(github_token=github_token)

    from langchain_anthropic import ChatAnthropic  # type: ignore[import]

    # We use a structured output LLM that returns a RepoSummary directly.
    # For the demo we use a simple approach: run the raw node which calls
    # llm.ainvoke with a plain prompt string and parse the output.
    llm = _make_structured_llm(settings)

    # -- Build and run the node ------------------------------------------------
    node = make_repo_analyzer_node(tools=tools, llm=llm)

    state: BlogState = {
        "user_id": user_id,
        "session_id": "demo-session",
        "phase": "repo",
        "messages": [],
        "repo_url": repo_url,
        "repo_summary": None,
        "intake_answers": {},
        "current_draft": None,
        "revision_history": [],
        "notion_page_id": None,
        "notion_title": None,
        "medium_markdown": None,
        "medium_url": None,
        "linkedin_post": None,
        "linkedin_post_url": None,
        "outreach_dm": None,
    }

    logger.info("Running repo_analyzer for: %s", repo_url)
    result = await node(state)

    summary: RepoSummary = result["repo_summary"]
    print("\n" + "=" * 60)
    print("REPO SUMMARY")
    print("=" * 60)
    print(f"Language      : {summary.language}")
    print(f"Purpose       : {summary.purpose}")
    print(f"Modules       : {', '.join(summary.modules)}")
    print(f"Notable commits:")
    for c in summary.notable_commits:
        print(f"  - {c}")
    print(f"README excerpt: {summary.readme_excerpt[:200]!r}")
    print("=" * 60)
    print(f"Next phase    : {result['phase']}")


def _make_structured_llm(settings: "Settings") -> "Any":  # type: ignore[name-defined]
    """Return an LLM wrapper that produces a RepoSummary from a prompt string.

    This wraps ChatAnthropic with a custom chain that parses the model output
    into a RepoSummary. In production the graph uses a more sophisticated
    approach; here we keep it simple for the demo.
    """
    from langchain_anthropic import ChatAnthropic  # type: ignore[import]
    from langchain_core.messages import HumanMessage
    from langchain_core.runnables import RunnableLambda

    from app.agent.state import RepoSummary

    chat = ChatAnthropic(
        model=settings.anthropic_model,
        api_key=settings.anthropic_api_key.get_secret_value(),
        max_tokens=1024,
    )

    async def _invoke(prompt: str) -> RepoSummary:
        system = (
            "You are an expert software analyst. "
            "Respond ONLY with a JSON object with these keys: "
            "language (str), modules (list of str), purpose (str, 1-2 sentences), "
            "notable_commits (list of str), readme_excerpt (str, first 500 chars of README). "
            "Do not include any other text."
        )
        messages = [HumanMessage(content=f"{system}\n\n{prompt}")]
        response = await chat.ainvoke(messages)
        import json

        data = json.loads(response.content)
        return RepoSummary(
            language=data.get("language", "unknown"),
            modules=tuple(data.get("modules", [])),
            purpose=data.get("purpose", ""),
            notable_commits=tuple(data.get("notable_commits", [])),
            readme_excerpt=data.get("readme_excerpt", ""),
        )

    return RunnableLambda(_invoke)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Analyze a GitHub repository via the repo_analyzer node.")
    parser.add_argument("repo_url", help="GitHub repository URL (e.g. https://github.com/owner/repo)")
    parser.add_argument(
        "--user-id",
        default="anonymous",
        help="User ID for token lookup in Supabase (default: anonymous)",
    )
    args = parser.parse_args()
    asyncio.run(main(args.repo_url, args.user_id))
