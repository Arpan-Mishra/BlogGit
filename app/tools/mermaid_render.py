"""
Mermaid diagram to image URL converter.

Uses mermaid.ink to render Mermaid diagrams as images via URL encoding.
Used by the Medium adapter to pre-render diagrams that Medium cannot
display natively.
"""

import base64


def mermaid_to_image_url(mermaid_code: str, output_format: str = "img") -> str:
    """Convert Mermaid diagram code to a mermaid.ink image URL.

    Parameters
    ----------
    mermaid_code:
        Raw Mermaid syntax (e.g. "graph LR\\n  A-->B").
    output_format:
        "img" for PNG, "svg" for SVG. Defaults to "img" (PNG).

    Returns
    -------
    A URL like ``https://mermaid.ink/img/<base64>``.
    """
    encoded = base64.urlsafe_b64encode(mermaid_code.encode("utf-8")).decode("ascii")
    return f"https://mermaid.ink/{output_format}/{encoded}"


def replace_mermaid_with_images(markdown: str) -> str:
    """Replace ```mermaid fences with mermaid.ink image URLs."""
    lines = markdown.split("\n")
    result: list[str] = []
    i = 0
    while i < len(lines):
        if lines[i].strip() == "```mermaid":
            mermaid_lines: list[str] = []
            i += 1
            while i < len(lines) and not lines[i].startswith("```"):
                mermaid_lines.append(lines[i])
                i += 1
            mermaid_code = "\n".join(mermaid_lines)
            img_url = mermaid_to_image_url(mermaid_code)
            result.append(f"![Diagram]({img_url})")
            i += 1
        else:
            result.append(lines[i])
            i += 1
    return "\n".join(result)
