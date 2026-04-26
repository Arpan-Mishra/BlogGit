"""
BlogGit — Streamlit chat UI.

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
import re
import uuid
from typing import Generator

import requests
import streamlit as st
import streamlit.components.v1 as components

import sys
from pathlib import Path

# Ensure the project root is on sys.path so both `streamlit run frontend/app.py`
# (cwd = project root) and direct script execution work correctly.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from frontend.components.connections import render_connections

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

import os
API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------


def _auth_headers() -> dict[str, str]:
    """Return Authorization header dict if user is logged in, else empty."""
    token = st.session_state.get("auth_token")
    if token:
        return {"Authorization": f"Bearer {token}"}
    return {}


def _load_user_connections() -> None:
    """Fetch connection statuses from backend and update session state."""
    try:
        resp = requests.get(
            f"{API_BASE_URL}/user/connections",
            headers=_auth_headers(),
            timeout=10,
        )
        if resp.ok:
            for conn in resp.json().get("connections", []):
                if conn["connected"]:
                    st.session_state[f"{conn['provider']}_connected"] = True
    except requests.exceptions.RequestException as exc:
        logger.warning("Failed to load user connections: %s", exc)


def _render_auth_page() -> None:
    """Render a login/signup page when the user is not authenticated."""
    st.title("BlogGit")
    st.caption("Turn your GitHub work into published blog posts.")
    st.markdown("---")

    login_tab, signup_tab = st.tabs(["Login", "Sign Up"])

    with login_tab:
        with st.form("login_form"):
            email = st.text_input("Email", key="login_email")
            password = st.text_input("Password", type="password", key="login_password")
            submitted = st.form_submit_button("Login", type="primary")

        if submitted:
            if not email or not password:
                st.error("Please enter both email and password.")
                return
            try:
                resp = requests.post(
                    f"{API_BASE_URL}/user/login",
                    json={"email": email, "password": password},
                    timeout=10,
                )
                if resp.ok:
                    data = resp.json()
                    st.session_state["auth_token"] = data["access_token"]
                    st.session_state["refresh_token"] = data["refresh_token"]
                    st.session_state["user_id"] = data["user_id"]
                    st.session_state["user_email"] = data["email"]
                    _load_user_connections()
                    st.rerun()
                else:
                    detail = resp.json().get("detail", "Login failed")
                    st.error(detail)
            except requests.exceptions.ConnectionError:
                st.error("Cannot connect to the backend.")

    with signup_tab:
        with st.form("signup_form"):
            email = st.text_input("Email", key="signup_email")
            password = st.text_input(
                "Password (min 8 characters)", type="password", key="signup_password"
            )
            submitted = st.form_submit_button("Sign Up", type="primary")

        if submitted:
            if not email or not password:
                st.error("Please enter both email and password.")
                return
            if len(password) < 8:
                st.error("Password must be at least 8 characters.")
                return
            try:
                resp = requests.post(
                    f"{API_BASE_URL}/user/signup",
                    json={"email": email, "password": password},
                    timeout=10,
                )
                if resp.ok:
                    data = resp.json()
                    if data.get("status") == "confirmation_pending":
                        st.success(data["message"])
                    else:
                        st.session_state["auth_token"] = data["access_token"]
                        st.session_state["refresh_token"] = data["refresh_token"]
                        st.session_state["user_id"] = data["user_id"]
                        st.session_state["user_email"] = data["email"]
                        _load_user_connections()
                        st.rerun()
                else:
                    detail = resp.json().get("detail", "Signup failed")
                    st.error(detail)
            except requests.exceptions.ConnectionError:
                st.error("Cannot connect to the backend.")

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
    data_buffer: list[str] = []
    try:
        with requests.post(
            f"{API_BASE_URL}/chat",
            json=payload,
            headers=_auth_headers(),
            stream=True,
            timeout=120,
        ) as resp:
            resp.raise_for_status()
            for raw_line in resp.iter_lines(decode_unicode=True):
                if not raw_line:
                    # Empty line = SSE event separator. Flush buffered data lines.
                    if data_buffer:
                        yield event_type, "\n".join(data_buffer)
                        data_buffer = []
                        event_type = "message"
                elif raw_line.startswith("event:"):
                    event_type = raw_line[6:].strip()
                elif raw_line.startswith("data:"):
                    # Accumulate lines; SSE spec joins multiple data: lines with \n
                    data_buffer.append(raw_line[5:].lstrip(" "))
            # Flush any trailing data that arrived without a final empty line
            if data_buffer:
                yield event_type, "\n".join(data_buffer)
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
    # Publish results
    if "notion_page_url" not in st.session_state:
        st.session_state["notion_page_url"] = None
    if "medium_markdown" not in st.session_state:
        st.session_state["medium_markdown"] = None
    if "linkedin_post" not in st.session_state:
        st.session_state["linkedin_post"] = None
    if "outreach_dm" not in st.session_state:
        st.session_state["outreach_dm"] = None


def _handle_logout() -> None:
    """Sign out the user and clear auth state."""
    token = st.session_state.get("auth_token")
    if token:
        try:
            requests.post(
                f"{API_BASE_URL}/user/logout",
                headers={"Authorization": f"Bearer {token}"},
                timeout=5,
            )
        except requests.exceptions.RequestException as exc:
            logger.warning("Logout request to backend failed: %s", exc)
    for key in list(st.session_state.keys()):
        del st.session_state[key]


def _render_sidebar() -> None:
    st.sidebar.title("BlogGit")
    st.sidebar.caption("Turn your GitHub work into published blog posts.")

    user_email = st.session_state.get("user_email", "")
    if user_email:
        st.sidebar.markdown(f"Logged in as **{user_email}**")
        if st.sidebar.button("Logout"):
            _handle_logout()
            st.rerun()
        st.sidebar.markdown("---")

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
        "outline": "Planning sections",
        "draft": "Drafting post",
        "revise": "Revising",
        "notion": "Published to Notion",
        "medium": "Medium content ready",
        "linkedin": "LinkedIn content ready",
        "done": "Complete",
    }
    st.sidebar.markdown(f"**Status:** {phase_labels.get(phase, phase)}")


def _render_chat_history() -> None:
    for msg in st.session_state["chat_history"]:
        with st.chat_message(msg["role"]):
            _render_message_content(msg["content"])


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
            if event_type == "token":
                full_response += data
                placeholder.markdown(full_response + "...")
            elif event_type == "tool_start":
                try:
                    tool_info = json.loads(data)
                    tool_name = tool_info.get("tool_name", "tool")
                except (json.JSONDecodeError, TypeError):
                    tool_name = "tool"
                if not full_response:
                    placeholder.markdown(f"*Using {tool_name}...*")
            elif event_type == "message":
                full_response += data
                placeholder.markdown(full_response + " ")
            elif event_type == "status":
                if not full_response:
                    placeholder.markdown(f"*{data}*")
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


_MERMAID_FENCE_RE = re.compile(r"```mermaid\n(.*?)\n```", re.DOTALL)


def _split_mermaid_blocks(content: str) -> list[tuple[str, str]]:
    """Split *content* into alternating text and mermaid diagram segments.

    Returns a list of ``(kind, text)`` tuples where *kind* is either
    ``"text"`` or ``"mermaid"``.
    """
    parts: list[tuple[str, str]] = []
    last = 0
    for m in _MERMAID_FENCE_RE.finditer(content):
        if m.start() > last:
            parts.append(("text", content[last : m.start()]))
        parts.append(("mermaid", m.group(1).strip()))
        last = m.end()
    if last < len(content):
        parts.append(("text", content[last:]))
    return parts


def _render_mermaid(diagram_code: str) -> None:
    """Render a Mermaid diagram via CDN inside an st.components iframe."""
    safe = diagram_code.replace("`", "\\`")
    uid = abs(hash(diagram_code)) % (10**8)
    html = f"""<!DOCTYPE html><html><body style="margin:0;background:#ffffff;">
<div id="m{uid}"></div>
<script type="module">
  import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs';
  mermaid.initialize({{
    startOnLoad: false,
    theme: 'base',
    themeVariables: {{
      background: '#ffffff',
      primaryColor: '#6366f1',
      primaryTextColor: '#ffffff',
      primaryBorderColor: '#4f46e5',
      secondaryColor: '#e0e7ff',
      secondaryTextColor: '#1f2937',
      secondaryBorderColor: '#818cf8',
      tertiaryColor: '#f3f4f6',
      tertiaryTextColor: '#1f2937',
      tertiaryBorderColor: '#d1d5db',
      lineColor: '#6b7280',
      edgeLabelBackground: '#f3f4f6',
      fontFamily: 'ui-sans-serif, system-ui, sans-serif',
      fontSize: '14px'
    }}
  }});
  const {{ svg }} = await mermaid.render('g{uid}', `{safe}`);
  document.getElementById('m{uid}').innerHTML = svg;
</script></body></html>"""
    components.html(html, height=450, scrolling=True)


def _render_message_content(content: str) -> None:
    """Render message content, converting Mermaid fences to live diagrams."""
    for part_type, part_content in _split_mermaid_blocks(content):
        if part_type == "mermaid":
            _render_mermaid(part_content)
        elif part_content.strip():
            st.markdown(part_content)


def _render_draft_panel() -> None:
    """Show the current draft in an expandable panel when in revise phase."""
    draft = st.session_state.get("current_draft")
    if not draft:
        return
    with st.expander("Current draft (click to expand)", expanded=False):
        _render_message_content(draft)
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


def _call_publish_api(endpoint: str, payload: dict) -> dict | None:
    """POST to a /publish/* endpoint; return JSON on success or None on error."""
    try:
        resp = requests.post(
            f"{API_BASE_URL}/publish/{endpoint}",
            json=payload,
            headers=_auth_headers(),
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.ConnectionError:
        st.error("Cannot connect to the backend. Is `uvicorn app.api.main:app` running?")
    except requests.exceptions.HTTPError as exc:
        try:
            detail = exc.response.json().get("detail", str(exc))
        except Exception:
            detail = str(exc)
        st.error(f"Publish error: {detail}")
    return None


def _render_publish_panel() -> None:
    """Render the multi-platform publish panel when a draft is available."""
    draft = st.session_state.get("current_draft")
    if not draft:
        return

    st.markdown("---")
    st.subheader("Publish")

    notion_tab, medium_tab, linkedin_tab = st.tabs(["Notion", "Medium", "LinkedIn"])

    # ------------------------------------------------------------------
    # Notion tab
    # ------------------------------------------------------------------
    with notion_tab:
        notion_token = st.session_state.get("notion_token", "")
        parent_page_id = st.session_state.get("notion_parent_page_id", "")

        if st.session_state.get("notion_page_url"):
            st.success("Published to Notion")
            st.markdown(f"[Open in Notion]({st.session_state['notion_page_url']})")
        else:
            if not notion_token:
                st.info("Add your Notion integration token in the sidebar to publish.")
            elif not parent_page_id:
                st.info("Add the Notion parent page ID in the sidebar.")
            else:
                if st.button("Publish to Notion", key="btn_publish_notion", type="primary"):
                    with st.spinner("Creating Notion page..."):
                        result = _call_publish_api(
                            "notion",
                            {
                                "session_id": st.session_state["session_id"],
                                "token": notion_token,
                                "parent_page_id": parent_page_id,
                            },
                        )
                    if result:
                        st.session_state["notion_page_url"] = result.get("page_url", "")
                        st.success(
                            f"Published: [{result.get('notion_title', 'View page')}]"
                            f"({result.get('page_url', '')})"
                        )
                        st.rerun()

    # ------------------------------------------------------------------
    # Medium tab
    # ------------------------------------------------------------------
    with medium_tab:
        medium_markdown = st.session_state.get("medium_markdown")

        if not medium_markdown:
            if st.button("Adapt for Medium", key="btn_adapt_medium", type="primary"):
                with st.spinner("Adapting draft for Medium (rendering diagrams)..."):
                    result = _call_publish_api(
                        "medium",
                        {"session_id": st.session_state["session_id"]},
                    )
                if result:
                    st.session_state["medium_markdown"] = result.get("medium_markdown", "")
                    st.rerun()
        else:
            st.success("Medium-ready content prepared. All diagrams rendered as images.")
            st.caption("Copy this content into Medium's editor — images will load automatically.")
            col_dl, col_reset = st.columns([3, 1])
            with col_dl:
                st.download_button(
                    label="Download Medium .md",
                    data=medium_markdown,
                    file_name="medium_post.md",
                    mime="text/markdown",
                    key="btn_download_medium",
                )
            with col_reset:
                st.button(
                    "Regenerate",
                    key="btn_regen_medium",
                    on_click=lambda: st.session_state.update({"medium_markdown": None}),
                )
            with st.expander("Preview Medium content", expanded=False):
                st.markdown(medium_markdown)

    # ------------------------------------------------------------------
    # LinkedIn tab
    # ------------------------------------------------------------------
    def _clear_linkedin() -> None:
        st.session_state["linkedin_post"] = None
        st.session_state["outreach_dm"] = None

    with linkedin_tab:
        linkedin_post = st.session_state.get("linkedin_post")
        outreach_dm = st.session_state.get("outreach_dm")

        if not linkedin_post:
            custom_instructions = st.text_area(
                "Custom instructions (optional)",
                placeholder="e.g., Focus on performance gains, mention Python 3.12, keep it casual...",
                key="linkedin_custom_instructions",
                height=80,
            )
            if st.button("Generate LinkedIn content", key="btn_gen_linkedin", type="primary"):
                with st.spinner("Generating LinkedIn post and outreach DM..."):
                    result = _call_publish_api(
                        "linkedin",
                        {
                            "session_id": st.session_state["session_id"],
                            "custom_instructions": custom_instructions or "",
                        },
                    )
                if result:
                    st.session_state["linkedin_post"] = result.get("linkedin_post", "")
                    st.session_state["outreach_dm"] = result.get("outreach_dm", "")
                    st.rerun()
        else:
            col_post, col_regen = st.columns([3, 1])
            with col_regen:
                st.button("Regenerate", key="btn_regen_linkedin", on_click=_clear_linkedin)

            st.markdown("**LinkedIn Post**")
            st.text_area(
                "LinkedIn post (copy and paste to LinkedIn)",
                value=linkedin_post,
                height=300,
                key="ta_linkedin_post",
                label_visibility="collapsed",
            )
            char_count = len(linkedin_post)
            st.caption(f"{char_count} characters")

            if outreach_dm:
                st.markdown("**Outreach DM**")
                st.text_area(
                    "Outreach DM (under 300 chars)",
                    value=outreach_dm,
                    height=100,
                    key="ta_outreach_dm",
                    label_visibility="collapsed",
                )
                dm_count = len(outreach_dm)
                color = "green" if dm_count <= 300 else "red"
                st.caption(f":{color}[{dm_count}/300 characters]")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    st.set_page_config(
        page_title="BlogGit",
        page_icon="",
        layout="wide",
    )

    _init_session()

    if "auth_token" not in st.session_state:
        _render_auth_page()
        return

    # Detect OAuth callback redirects (e.g. ?connected=linkedin after OAuth flow)
    _connected_provider = st.query_params.get("connected")
    if _connected_provider:
        st.session_state[f"{_connected_provider}_connected"] = True
        st.query_params.clear()
        st.toast(f"{_connected_provider.capitalize()} connected!", icon="✅")

    _render_sidebar()

    st.title("BlogGit")
    st.caption("Tell me about your project and I'll help write a blog post.")

    if not st.session_state["repo_url_submitted"]:
        st.info("Enter a GitHub repository URL in the sidebar and click **Start session** to begin.")
        return

    _render_chat_history()
    _render_draft_panel()
    _render_publish_panel()

    # Chat input — shown for all phases except "done"
    if st.session_state["phase"] != "done":
        placeholder_text = {
            "repo": "Say anything to start the analysis...",
            "intake": "Answer the question above...",
            "outline": "Approve the outline or suggest changes...",
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
