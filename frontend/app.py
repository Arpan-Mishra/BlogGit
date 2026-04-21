"""
Blog Copilot — Streamlit chat UI.

Connects to the FastAPI /chat endpoint and streams responses via SSE.

Session flow:
  1. User pastes a GitHub repo URL and submits their first message.
  2. The agent analyses the repo, then asks 5 intake questions one by one.
  3. After all answers are collected, the agent produces a draft blog post.
  4. The user can type revision feedback; the agent revises until satisfied.

Usage:
    streamlit run frontend/app.py
"""

import json
import logging
import uuid
from typing import Generator

import requests
import streamlit as st

from frontend.components.connections import render_connections

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

API_BASE_URL = "http://localhost:8000"

# ---------------------------------------------------------------------------
# SSE helper
# ---------------------------------------------------------------------------


def _stream_chat(
    *,
    session_id: str,
    user_id: str,
    message: str,
    repo_url: str | None = None,
    github_token: str | None = None,
) -> Generator[tuple[str, str], None, None]:
    """POST to /chat and yield (event_type, data) pairs from the SSE stream.

    Yields
    ------
    tuple[str, str]
        ``(event_type, data)`` where event_type is one of ``"message"`` or
        ``"done"``.
    """
    payload: dict = {
        "session_id": session_id,
        "user_id": user_id,
        "message": message,
    }
    if repo_url:
        payload["repo_url"] = repo_url
    if github_token:
        payload["github_token"] = github_token

    event_type = "message"
    try:
        with requests.post(
            f"{API_BASE_URL}/chat",
            json=payload,
            stream=True,
            timeout=120,
        ) as resp:
            resp.raise_for_status()
            for raw_line in resp.iter_lines(decode_unicode=True):
                if not raw_line:
                    continue
                if raw_line.startswith("event:"):
                    event_type = raw_line[6:].strip()
                elif raw_line.startswith("data:"):
                    data = raw_line[5:].strip()
                    yield event_type, data
                    event_type = "message"  # reset after each data line
    except requests.exceptions.ConnectionError:
        yield "error", "Cannot connect to the backend. Is `uvicorn app.api.main:app` running?"
    except requests.exceptions.HTTPError as exc:
        try:
            detail = exc.response.json().get("detail", str(exc))
        except Exception:
            detail = str(exc)
        yield "error", detail


# ---------------------------------------------------------------------------
# Page setup
# ---------------------------------------------------------------------------


def _init_session() -> None:
    """Initialise all required st.session_state keys on first load."""
    if "session_id" not in st.session_state:
        st.session_state["session_id"] = str(uuid.uuid4())
    if "user_id" not in st.session_state:
        st.session_state["user_id"] = "anonymous"
    if "chat_history" not in st.session_state:
        # list of {"role": "user"|"assistant", "content": str}
        st.session_state["chat_history"] = []
    if "phase" not in st.session_state:
        st.session_state["phase"] = "repo"
    if "current_draft" not in st.session_state:
        st.session_state["current_draft"] = None
    if "repo_url_submitted" not in st.session_state:
        st.session_state["repo_url_submitted"] = False
    if "repo_url" not in st.session_state:
        st.session_state["repo_url"] = ""
    if "github_token" not in st.session_state:
        st.session_state["github_token"] = ""


def _render_sidebar() -> None:
    st.sidebar.title("Blog Copilot")
    st.sidebar.caption("Turn your GitHub work into published blog posts.")

    # Repo URL input (only editable before session starts)
    if not st.session_state["repo_url_submitted"]:
        repo_url = st.sidebar.text_input(
            "GitHub repository URL",
            placeholder="https://github.com/owner/repo",
            key="_repo_url_input",
        )
        if st.sidebar.button("Start session", type="primary"):
            if repo_url.strip():
                st.session_state["repo_url"] = repo_url.strip()
                st.session_state["repo_url_submitted"] = True
                st.rerun()
            else:
                st.sidebar.error("Please enter a repository URL.")
    else:
        st.sidebar.success(f"Repo: {st.session_state['repo_url']}")
        if st.sidebar.button("New session"):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()

    render_connections(api_base_url=API_BASE_URL)

    # Phase indicator
    phase = st.session_state.get("phase", "repo")
    phase_labels = {
        "repo": "Analysing repository",
        "intake": "Gathering requirements",
        "draft": "Drafting post",
        "revise": "Revising",
        "done": "Complete",
    }
    st.sidebar.markdown(f"**Status:** {phase_labels.get(phase, phase)}")


def _render_chat_history() -> None:
    for msg in st.session_state["chat_history"]:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])


def _handle_user_input(user_input: str) -> None:
    """Append the user message, call /chat, stream the response."""
    st.session_state["chat_history"].append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    # On the very first message pass the repo_url so the backend initialises state.
    is_first_message = len(st.session_state["chat_history"]) == 1
    repo_url = st.session_state["repo_url"] if is_first_message else None

    full_response = ""
    phase_after = st.session_state["phase"]

    with st.chat_message("assistant"):
        placeholder = st.empty()
        for event_type, data in _stream_chat(
            session_id=st.session_state["session_id"],
            user_id=st.session_state["user_id"],
            message=user_input,
            repo_url=repo_url,
            github_token=st.session_state.get("github_token"),
        ):
            if event_type == "message":
                full_response += data
                placeholder.markdown(full_response + " ")
            elif event_type == "done":
                phase_after = data
            elif event_type == "error":
                st.error(data)
                return

    if full_response:
        placeholder.markdown(full_response)
        st.session_state["chat_history"].append(
            {"role": "assistant", "content": full_response}
        )
        # If this looks like a full draft (longer content in revise phase) cache it.
        if phase_after == "revise" and len(full_response) > 200:
            st.session_state["current_draft"] = full_response

    st.session_state["phase"] = phase_after


def _render_draft_panel() -> None:
    """Show the current draft in an expandable panel when in revise phase."""
    draft = st.session_state.get("current_draft")
    if not draft:
        return
    with st.expander("Current draft (click to expand)", expanded=False):
        st.markdown(draft)
        col1, col2 = st.columns(2)
        with col1:
            if st.button("Copy to clipboard", key="btn_copy_draft"):
                st.write("Use Cmd/Ctrl+A in the expander to select all text, then copy.")
        with col2:
            st.download_button(
                label="Download as .md",
                data=draft,
                file_name="blog_post_draft.md",
                mime="text/markdown",
                key="btn_download_draft",
            )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    st.set_page_config(
        page_title="Blog Copilot",
        page_icon="",
        layout="wide",
    )

    _init_session()
    _render_sidebar()

    st.title("Blog Copilot")
    st.caption("Tell me about your project and I'll help write a blog post.")

    if not st.session_state["repo_url_submitted"]:
        st.info("Enter a GitHub repository URL in the sidebar and click **Start session** to begin.")
        return

    _render_chat_history()
    _render_draft_panel()

    # Chat input — shown for all phases except "done"
    if st.session_state["phase"] != "done":
        placeholder_text = {
            "repo": "Say anything to start the analysis...",
            "intake": "Answer the question above...",
            "draft": "Say anything to start drafting...",
            "revise": "Give feedback on the draft (e.g. 'make the intro shorter')...",
        }.get(st.session_state["phase"], "Type a message...")

        user_input = st.chat_input(placeholder_text)
        if user_input:
            _handle_user_input(user_input)
            st.rerun()
    else:
        st.success("Draft complete! Use the panel above to download or copy your post.")


if __name__ == "__main__":
    main()
