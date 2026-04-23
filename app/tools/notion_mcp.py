"""
Notion REST API client for Blog Copilot.

Provides create_notion_page() which converts a markdown blog post into
Notion blocks and publishes it under a specified parent page.

Authentication: pass a Notion integration token or OAuth access token.
Both use the same Bearer auth scheme.

Notion API reference: https://developers.notion.com/reference
"""

import logging
import re
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_NOTION_API_BASE = "https://api.notion.com/v1"
_NOTION_VERSION = "2022-06-28"
_MAX_RICH_TEXT_LENGTH = 1990  # Notion limit is 2000; use 1990 for safety
_MAX_BLOCKS_PER_BATCH = 100   # Notion limit per PATCH request

# Languages Notion's code block accepts (subset — covers most common cases)
_NOTION_LANGUAGES = frozenset({
    "abap", "arduino", "bash", "basic", "c", "clojure", "coffeescript",
    "cpp", "css", "dart", "diff", "docker", "elixir", "elm", "erlang",
    "flow", "fortran", "fsharp", "gherkin", "glsl", "go", "graphql",
    "groovy", "haskell", "html", "java", "javascript", "json", "julia",
    "kotlin", "latex", "less", "lisp", "livescript", "lua", "makefile",
    "markdown", "markup", "matlab", "mermaid", "nix", "objective-c",
    "ocaml", "pascal", "perl", "php", "plain text", "powershell",
    "prolog", "protobuf", "python", "r", "reason", "ruby", "rust",
    "sass", "scala", "scheme", "scss", "shell", "sql", "swift",
    "toml", "typescript", "vb.net", "verilog", "vhdl", "visual basic",
    "webassembly", "xml", "yaml", "java/c/c++/c#",
})


# ---------------------------------------------------------------------------
# Internal helpers — Notion block constructors
# ---------------------------------------------------------------------------


def _rich_text(content: str) -> list[dict]:
    """Return a rich_text array chunked to respect Notion's 2000-char limit."""
    if not content:
        return [{"type": "text", "text": {"content": ""}}]
    chunks = [
        content[i: i + _MAX_RICH_TEXT_LENGTH]
        for i in range(0, len(content), _MAX_RICH_TEXT_LENGTH)
    ]
    return [{"type": "text", "text": {"content": c}} for c in chunks]


def _heading_block(level: int, text: str) -> dict:
    key = f"heading_{level}"
    return {"object": "block", "type": key, key: {"rich_text": _rich_text(text)}}


def _paragraph_block(text: str) -> dict:
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": _rich_text(text)},
    }


def _bullet_block(text: str) -> dict:
    return {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {"rich_text": _rich_text(text)},
    }


def _numbered_block(text: str) -> dict:
    return {
        "object": "block",
        "type": "numbered_list_item",
        "numbered_list_item": {"rich_text": _rich_text(text)},
    }


def _divider_block() -> dict:
    return {"object": "block", "type": "divider", "divider": {}}


def _image_block(url: str, caption: str = "") -> dict:
    """Return a Notion image block for an external URL."""
    cap_rt = _rich_text(caption) if caption else []
    return {
        "object": "block",
        "type": "image",
        "image": {
            "type": "external",
            "external": {"url": url},
            "caption": cap_rt,
        },
    }


def _code_block(code: str, language: str) -> list[dict]:
    """Return one or more code blocks (Notion code blocks have a char limit)."""
    lang = language.lower().strip() if language else "plain text"
    if lang not in _NOTION_LANGUAGES:
        lang = "plain text"

    # Split code that exceeds the rich-text limit
    chunks = [
        code[i: i + _MAX_RICH_TEXT_LENGTH]
        for i in range(0, max(len(code), 1), _MAX_RICH_TEXT_LENGTH)
    ]
    return [
        {
            "object": "block",
            "type": "code",
            "code": {
                "rich_text": [{"type": "text", "text": {"content": chunk}}],
                "language": lang,
            },
        }
        for chunk in chunks
    ]


# ---------------------------------------------------------------------------
# Markdown → Notion blocks converter
# ---------------------------------------------------------------------------


def markdown_to_notion_blocks(content: str) -> list[dict]:
    """Convert a markdown string into a list of Notion block objects.

    Handles:
    - ATX headings (``# / ## / ###``)
    - Fenced code blocks (`` ``` ``)
    - Unordered list items (``-`` or ``*``)
    - Ordered list items (``1. 2.`` etc.)
    - Horizontal rules (``---`` / ``***`` / ``___``)
    - Plain paragraphs (non-empty lines)
    - Empty lines (skipped — Notion renders spacing automatically)

    Returns
    -------
    list[dict]
        Ready to pass as ``children`` in a Notion API call.
    """
    blocks: list[dict] = []
    lines = content.split("\n")
    i = 0

    while i < len(lines):
        line = lines[i]

        # --- Image markdown ---
        image_match = re.match(r'^!\[([^\]]*)\]\(([^)]+)\)', line.strip())
        if image_match:
            blocks.append(_image_block(image_match.group(2), image_match.group(1)))
            i += 1
            continue

        # --- Fenced code block ---
        if line.startswith("```"):
            lang = line[3:].strip()
            code_lines: list[str] = []
            i += 1
            while i < len(lines) and not lines[i].startswith("```"):
                code_lines.append(lines[i])
                i += 1
            code_text = "\n".join(code_lines)
            blocks.extend(_code_block(code_text, lang))
            i += 1  # skip closing fence
            continue

        # --- ATX headings ---
        if line.startswith("### "):
            blocks.append(_heading_block(3, line[4:].strip()))
        elif line.startswith("## "):
            blocks.append(_heading_block(2, line[3:].strip()))
        elif line.startswith("# "):
            blocks.append(_heading_block(1, line[2:].strip()))

        # --- Unordered list ---
        elif line.startswith("- ") or line.startswith("* "):
            blocks.append(_bullet_block(line[2:].strip()))

        # --- Ordered list (e.g. "1. ", "10. ") ---
        elif re.match(r"^\d+\. ", line):
            text = re.sub(r"^\d+\. ", "", line).strip()
            blocks.append(_numbered_block(text))

        # --- Horizontal rule ---
        elif line.strip() in ("---", "***", "___"):
            blocks.append(_divider_block())

        # --- Non-empty line → paragraph ---
        elif line.strip():
            blocks.append(_paragraph_block(line))

        # --- Empty line — skip ---
        i += 1

    return blocks


# ---------------------------------------------------------------------------
# Title extraction helper
# ---------------------------------------------------------------------------


def extract_title_from_markdown(content: str) -> str:
    """Return the first H1 heading from *content*, or 'Blog Post' if none found."""
    for line in content.split("\n"):
        if line.startswith("# "):
            return line[2:].strip()
    return "Blog Post"


# ---------------------------------------------------------------------------
# Notion API client
# ---------------------------------------------------------------------------


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": _NOTION_VERSION,
        "Content-Type": "application/json",
    }


def parse_notion_page_id(raw: str) -> str:
    """Extract a 32-char hex page ID from a Notion URL or raw UUID."""
    cleaned = raw.strip().split("?")[0]
    # For URLs, take the last path segment (contains the ID)
    segment = cleaned.rsplit("/", 1)[-1]
    no_dashes = segment.replace("-", "")
    # The page ID is always the trailing 32 hex chars
    match = re.search(r"[a-f0-9]{32}$", no_dashes)
    if not match:
        raise ValueError(f"Cannot extract Notion page ID from: {raw!r}")
    return match.group(0)


def _normalise_page_id(page_id: str) -> str:
    """Accept Notion page IDs with or without dashes; normalise to UUID format."""
    raw = page_id.strip().replace("-", "")
    if len(raw) == 32:
        return f"{raw[:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:]}"
    return page_id.strip()


async def create_notion_page(
    *,
    token: str,
    parent_page_id: str,
    title: str,
    content: str,
) -> str:
    """Create a Notion page with *content* rendered as Notion blocks.

    Parameters
    ----------
    token:
        Notion integration token or OAuth access token.
    parent_page_id:
        UUID of the parent page (with or without dashes).
    title:
        Title for the new page.
    content:
        Markdown text to convert to Notion blocks.

    Returns
    -------
    str
        The URL of the newly created Notion page.

    Raises
    ------
    httpx.HTTPStatusError
        On any non-2xx response from the Notion API.
    """
    normalised_parent = _normalise_page_id(parent_page_id)
    blocks = markdown_to_notion_blocks(content)

    async with httpx.AsyncClient(timeout=30.0) as client:
        # 1. Create the page (title only — blocks added next)
        create_payload: dict[str, Any] = {
            "parent": {"page_id": normalised_parent},
            "properties": {
                "title": {
                    "title": [{"type": "text", "text": {"content": title[:2000]}}]
                }
            },
        }
        resp = await client.post(
            f"{_NOTION_API_BASE}/pages",
            headers=_headers(token),
            json=create_payload,
        )
        resp.raise_for_status()
        page = resp.json()
        page_id: str = page["id"]
        page_url: str = page.get("url", f"https://notion.so/{page_id.replace('-', '')}")

        # 2. Append content blocks in batches of _MAX_BLOCKS_PER_BATCH
        for batch_start in range(0, len(blocks), _MAX_BLOCKS_PER_BATCH):
            batch = blocks[batch_start: batch_start + _MAX_BLOCKS_PER_BATCH]
            patch_resp = await client.patch(
                f"{_NOTION_API_BASE}/blocks/{page_id}/children",
                headers=_headers(token),
                json={"children": batch},
            )
            patch_resp.raise_for_status()
            logger.debug(
                "Appended Notion blocks %d–%d for page %s",
                batch_start,
                batch_start + len(batch) - 1,
                page_id,
            )

    logger.info("Notion page created: %s (%s)", title, page_url)
    return page_url
