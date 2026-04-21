"""
OAuth connection status widgets for the Blog Copilot sidebar.

Displays the connection state for each platform (GitHub, Notion, LinkedIn,
Medium) and provides action buttons or token inputs for connecting them.

In v1 the connection state is read from the FastAPI backend via a simple
status endpoint. Buttons trigger the OAuth redirect flow.
"""

import streamlit as st

_PROVIDERS = [
    {
        "key": "github",
        "label": "GitHub",
        "icon": "",
        "description": "Required to read repositories",
    },
    {
        "key": "notion",
        "label": "Notion",
        "icon": "",
        "description": "Required to publish blog posts",
    },
    {
        "key": "linkedin",
        "label": "LinkedIn",
        "icon": "",
        "description": "Optional — post to LinkedIn",
    },
]


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

    # GitHub — token-based for v1 (OAuth in Sprint 7)
    _render_github_connection(github_token_key)

    # Notion, LinkedIn — OAuth placeholders
    for provider in _PROVIDERS[1:]:
        _render_oauth_placeholder(provider, api_base_url)

    # Medium — integration token
    _render_medium_token()

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


def _render_oauth_placeholder(provider: dict, api_base_url: str) -> None:
    connected = st.session_state.get(f"connected_{provider['key']}", False)
    label = provider["label"] + (" (connected)" if connected else "")
    with st.sidebar.expander(label, expanded=False):
        st.caption(provider["description"])
        if connected:
            if st.button(f"Disconnect {provider['label']}", key=f"btn_disconnect_{provider['key']}"):
                st.session_state[f"connected_{provider['key']}"] = False
                st.rerun()
        else:
            if st.button(f"Connect {provider['label']}", key=f"btn_connect_{provider['key']}"):
                # In Sprint 7 this opens the OAuth flow via a redirect.
                # For now, show a placeholder message.
                st.info(f"OAuth for {provider['label']} will be available in Sprint 7.")


def _render_medium_token() -> None:
    token = st.session_state.get("medium_token", "")
    connected = bool(token)
    label = "Medium" + (" (connected)" if connected else "")
    with st.sidebar.expander(label, expanded=False):
        st.caption("Optional — publish to Medium. Get your token at "
                   "medium.com/me/settings/security under 'Integration tokens'.")
        new_token = st.text_input(
            "Medium integration token",
            value=token,
            type="password",
            key="_medium_token_input",
            label_visibility="collapsed",
        )
        if new_token != token:
            st.session_state["medium_token"] = new_token
            st.rerun()
