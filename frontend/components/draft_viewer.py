"""
Read-only past-draft viewer with Notion / Medium / LinkedIn publish panel.

Used by frontend/app.py when the user selects a draft from the sidebar.
"""

import logging
import re
import sys
from pathlib import Path

import requests
import streamlit as st
import streamlit.components.v1 as components

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_MERMAID_FENCE_RE = re.compile(r"```mermaid\n(.*?)\n```", re.DOTALL)


# ---------------------------------------------------------------------------
# Rendering helpers (duplicated from frontend/app.py to avoid circular import)
# ---------------------------------------------------------------------------


def _split_mermaid_blocks(content: str) -> list[tuple[str, str]]:
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


def _render_content(content: str) -> None:
    for part_type, part_content in _split_mermaid_blocks(content):
        if part_type == "mermaid":
            _render_mermaid(part_content)
        elif part_content.strip():
            st.markdown(part_content)


# ---------------------------------------------------------------------------
# Publish API helper
# ---------------------------------------------------------------------------


def _call_publish(
    endpoint: str,
    payload: dict,
    *,
    api_base_url: str,
    auth_headers: dict,
) -> dict | None:
    try:
        resp = requests.post(
            f"{api_base_url}/publish/{endpoint}",
            json=payload,
            headers=auth_headers,
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.ConnectionError:
        st.error("Cannot connect to the backend.")
    except requests.exceptions.HTTPError as exc:
        try:
            detail = exc.response.json().get("detail", str(exc))
        except Exception:
            detail = str(exc)
        st.error(f"Publish error: {detail}")
    return None


# ---------------------------------------------------------------------------
# Main render function
# ---------------------------------------------------------------------------


def render_draft_viewer(
    *,
    draft: dict,
    api_base_url: str,
    auth_headers: dict,
) -> None:
    """Render a read-only past draft with publish options."""
    title = draft.get("title") or draft.get("repo_url", "Draft")
    session_id = draft["session_id"]

    st.title(title)
    st.caption(f"Repo: {draft.get('repo_url', '')}")
    st.markdown("---")

    with st.expander("Draft content", expanded=True):
        _render_content(draft.get("current_draft", ""))

        col_dl, _ = st.columns([1, 3])
        with col_dl:
            st.download_button(
                label="Download .md",
                data=draft.get("current_draft", ""),
                file_name="draft.md",
                mime="text/markdown",
                key=f"dl_{session_id}",
            )

    st.markdown("---")
    st.subheader("Publish")

    notion_tab, medium_tab, linkedin_tab = st.tabs(["Notion", "Medium", "LinkedIn"])

    # ------------------------------------------------------------------
    # Notion tab
    # ------------------------------------------------------------------
    with notion_tab:
        notion_page_id = draft.get("notion_page_id")
        notion_title = draft.get("notion_title")
        if notion_page_id:
            page_url = f"https://notion.so/{notion_page_id.replace('-', '')}"
            st.success("Already published to Notion")
            st.markdown(f"[{notion_title or 'Open in Notion'}]({page_url})")
        else:
            notion_token = st.session_state.get("notion_token", "")
            parent_page_id = st.session_state.get("notion_parent_page_id", "")
            if not notion_token:
                st.info("Connect Notion in the sidebar to publish.")
            elif not parent_page_id:
                st.info("Add the Notion parent page ID in the sidebar.")
            else:
                if st.button("Publish to Notion", key=f"notion_{session_id}", type="primary"):
                    with st.spinner("Creating Notion page..."):
                        result = _call_publish(
                            "notion",
                            {
                                "session_id": session_id,
                                "token": notion_token,
                                "parent_page_id": parent_page_id,
                            },
                            api_base_url=api_base_url,
                            auth_headers=auth_headers,
                        )
                    if result:
                        page_url = result.get("page_url", "")
                        st.success(
                            f"Published: [{result.get('notion_title', 'View page')}]({page_url})"
                        )
                        draft["notion_page_id"] = result.get("notion_page_id")
                        draft["notion_title"] = result.get("notion_title")
                        st.rerun()

    # ------------------------------------------------------------------
    # Medium tab
    # ------------------------------------------------------------------
    with medium_tab:
        medium_markdown = draft.get("medium_markdown")
        if not medium_markdown:
            if st.button("Adapt for Medium", key=f"medium_{session_id}", type="primary"):
                with st.spinner("Adapting draft for Medium..."):
                    result = _call_publish(
                        "medium",
                        {"session_id": session_id},
                        api_base_url=api_base_url,
                        auth_headers=auth_headers,
                    )
                if result:
                    medium_markdown = result.get("medium_markdown", "")
                    draft["medium_markdown"] = medium_markdown
                    st.rerun()
        else:
            st.success("Medium-ready content prepared.")
            st.caption("Copy into Medium's editor — images will load automatically.")
            st.download_button(
                label="Download Medium .md",
                data=medium_markdown,
                file_name="medium_post.md",
                mime="text/markdown",
                key=f"dl_medium_{session_id}",
            )
            with st.expander("Preview Medium content", expanded=False):
                st.markdown(medium_markdown)

    # ------------------------------------------------------------------
    # LinkedIn tab
    # ------------------------------------------------------------------
    with linkedin_tab:
        linkedin_post = draft.get("linkedin_post")
        outreach_dm = draft.get("outreach_dm")

        if not linkedin_post:
            custom_instructions = st.text_area(
                "Custom instructions (optional)",
                placeholder="e.g., Focus on performance gains, keep it casual...",
                key=f"li_custom_{session_id}",
                height=80,
            )
            if st.button(
                "Generate LinkedIn content", key=f"linkedin_{session_id}", type="primary"
            ):
                with st.spinner("Generating LinkedIn post and outreach DM..."):
                    result = _call_publish(
                        "linkedin",
                        {
                            "session_id": session_id,
                            "custom_instructions": custom_instructions or "",
                        },
                        api_base_url=api_base_url,
                        auth_headers=auth_headers,
                    )
                if result:
                    draft["linkedin_post"] = result.get("linkedin_post", "")
                    draft["outreach_dm"] = result.get("outreach_dm", "")
                    st.rerun()
        else:
            st.markdown("**LinkedIn Post**")
            st.text_area(
                "LinkedIn post (copy and paste to LinkedIn)",
                value=linkedin_post,
                height=300,
                key=f"ta_li_{session_id}",
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
                    key=f"ta_dm_{session_id}",
                    label_visibility="collapsed",
                )
                dm_count = len(outreach_dm)
                color = "green" if dm_count <= 300 else "red"
                st.caption(f":{color}[{dm_count}/300 characters]")
