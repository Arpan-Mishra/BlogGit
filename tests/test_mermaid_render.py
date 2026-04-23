"""
Tests for app/tools/mermaid_render.py — Mermaid-to-image URL utility.
"""

import base64

from app.tools.mermaid_render import mermaid_to_image_url, replace_mermaid_with_images


class TestMermaidToImageUrl:
    def test_simple_flowchart_url(self) -> None:
        code = "graph LR\n  A-->B"
        url = mermaid_to_image_url(code)
        assert url.startswith("https://mermaid.ink/img/")

    def test_url_is_valid_base64(self) -> None:
        code = "graph LR\n  A-->B"
        url = mermaid_to_image_url(code)
        encoded_part = url.split("https://mermaid.ink/img/")[1]
        decoded = base64.urlsafe_b64decode(encoded_part).decode("utf-8")
        assert decoded == code

    def test_svg_format(self) -> None:
        code = "graph TD\n  X-->Y"
        url = mermaid_to_image_url(code, output_format="svg")
        assert url.startswith("https://mermaid.ink/svg/")

    def test_default_format_is_img(self) -> None:
        url = mermaid_to_image_url("graph LR\n  A-->B")
        assert "/img/" in url


class TestReplaceMermaidWithImages:
    def test_replaces_mermaid_fence(self) -> None:
        md = "Some text.\n\n```mermaid\ngraph LR\n  A-->B\n```\n\nMore text."
        result = replace_mermaid_with_images(md)
        assert "```mermaid" not in result
        assert "![Diagram](" in result
        assert "mermaid.ink" in result
        assert "Some text." in result
        assert "More text." in result

    def test_preserves_regular_code_blocks(self) -> None:
        md = "```python\nprint('hello')\n```"
        result = replace_mermaid_with_images(md)
        assert result == md

    def test_preserves_regular_images(self) -> None:
        md = "![Photo](https://images.unsplash.com/photo-123)"
        result = replace_mermaid_with_images(md)
        assert result == md

    def test_multiple_mermaid_blocks(self) -> None:
        md = "```mermaid\ngraph LR\n  A-->B\n```\n\n```mermaid\ngraph TD\n  X-->Y\n```"
        result = replace_mermaid_with_images(md)
        assert result.count("![Diagram](") == 2
        assert "```mermaid" not in result

    def test_no_mermaid_returns_unchanged(self) -> None:
        md = "Just some plain text.\n\nWith paragraphs."
        result = replace_mermaid_with_images(md)
        assert result == md
