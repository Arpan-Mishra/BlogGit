"""
Shared in-memory session store for Blog Copilot.

Both the /chat and /publish routes read from and write to this dict so that
the publish endpoints can access the draft produced during the chat session.

This will be replaced by a database-backed checkpointer in Sprint 7.
"""

from app.agent.state import BlogState

_sessions: dict[str, BlogState] = {}
