"""
OAuth connection status widgets for the BlogGit sidebar.

Displays the connection state for each platform (GitHub, Notion, LinkedIn,
Medium) and provides action buttons or token inputs for connecting them.

In v1 the connection state is read from the FastAPI backend via a simple
status endpoint. Buttons trigger the OAuth redirect flow.
"""

import re

import streamlit as st


def _parse_notion_page_id(raw: str) -> str:
    """Extract a 32-char hex page ID from a Notion URL or raw UUID."""
    cleaned = raw.strip().split("?")[0]
    segment = cleaned.rsplit("/", 1)[-1]
    no_dashes = segment.replace("-", "")
    match = re.search(r"[a-f0-9]{32}$", no_dashes)
    if not match:
        raise ValueError(f"Cannot extract Notion page ID from: {raw!r}")
    return match.group(0)


def render_connections(api_base_url: str, github_token_key: str = "github_token") -> None:
    """Render connection status cards in the Streamlit sidebar.

    Parameters
    ----------
    api_base_url:
        Root URL of the FastAPI backend (e.g. ``http://localhost:8000``).
    github_token_key:
        The ``st.session_state`` key used to store the GitHub token.
        Defaults to ``"github_token"``.
    """
    st.sidebar.markdown("### Connections")

    _render_github_connection(github_token_key)
    _render_notion_connection()
    _render_linkedin_connection(api_base_url)

    st.sidebar.divider()


def _render_github_connection(token_key: str) -> None:
    token = st.session_state.get(token_key, "")
    connected = bool(token)

    with st.sidebar.expander("GitHub" + (" (connected)" if connected else ""), expanded=not connected):
        st.markdown("Paste your [GitHub personal access token](https://github.com/settings/tokens) "
                    "(needs `repo` scope).")
        new_token = st.text_input(
            "GitHub token",
            value=token,
            type="password",
            key="_github_token_input",
            label_visibility="collapsed",
        )
        if new_token != token:
            st.session_state[token_key] = new_token
            st.rerun()


def _render_notion_connection() -> None:
    token = st.session_state.get("notion_token", "")
    page_id = st.session_state.get("notion_parent_page_id", "")
    connected = bool(token)

    label = "Notion" + (" (connected)" if connected else "")
    with st.sidebar.expander(label, expanded=not connected):
        st.caption(
            "Paste your [Notion integration token](https://www.notion.so/my-integrations) "
            "and the parent page ID where posts will be created."
        )
        new_token = st.text_input(
            "Notion token",
            value=token,
            type="password",
            key="_notion_token_input",
            label_visibility="collapsed",
            placeholder="secret_...",
        )
        new_page_id_raw = st.text_input(
            "Parent page ID",
            value=page_id,
            key="_notion_page_id_input",
            label_visibility="collapsed",
            placeholder="Notion page URL or page ID",
        )
        if new_token != token:
            st.session_state["notion_token"] = new_token
            st.rerun()
        if new_page_id_raw != page_id:
            if new_page_id_raw.strip():
                try:
                    parsed_id = _parse_notion_page_id(new_page_id_raw)
                    st.session_state["notion_parent_page_id"] = parsed_id
                    st.rerun()
                except ValueError:
                    st.error("Could not extract a Notion page ID. Paste a Notion URL or 32-char ID.")
            else:
                st.session_state["notion_parent_page_id"] = ""
                st.rerun()


def _render_linkedin_connection(api_base_url: str) -> None:
    connected = st.session_state.get("linkedin_connected", False)
    label = "LinkedIn" + (" (connected)" if connected else "")
    with st.sidebar.expander(label, expanded=not connected):
        st.caption("Optional — generate a LinkedIn post from your draft.")
        if connected:
            st.success("LinkedIn connected.")
            if st.button("Disconnect", key="_linkedin_disconnect"):
                st.session_state["linkedin_connected"] = False
                st.rerun()
        else:
            oauth_url = f"{api_base_url}/auth/linkedin/start"
            st.markdown(
                f'<a href="{oauth_url}" target="_self" '
                f'style="display:inline-block;padding:0.4rem 1rem;'
                f'background-color:#0a66c2;color:white;border-radius:0.5rem;'
                f'text-decoration:none;font-weight:600;text-align:center;">'
                f'Connect LinkedIn</a>',
                unsafe_allow_html=True,
            )
            st.caption("You will be redirected to LinkedIn to authorise and then returned here.")


