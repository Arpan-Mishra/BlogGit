"""
Tests for app/tools/notion_mcp.py — markdown_to_notion_blocks,
extract_title_from_markdown, _normalise_page_id, and create_notion_page.
"""

import pytest
import httpx


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class TestRichText:
    def test_empty_string_returns_single_empty_chunk(self) -> None:
        from app.tools.notion_mcp import _rich_text

        result = _rich_text("")
        assert result == [{"type": "text", "text": {"content": ""}}]

    def test_short_string_returns_single_chunk(self) -> None:
        from app.tools.notion_mcp import _rich_text

        result = _rich_text("hello")
        assert len(result) == 1
        assert result[0]["text"]["content"] == "hello"

    def test_long_string_is_chunked(self) -> None:
        from app.tools.notion_mcp import _rich_text, _MAX_RICH_TEXT_LENGTH

        long_text = "x" * (_MAX_RICH_TEXT_LENGTH + 10)
        result = _rich_text(long_text)
        assert len(result) == 2
        assert len(result[0]["text"]["content"]) == _MAX_RICH_TEXT_LENGTH
        assert len(result[1]["text"]["content"]) == 10


class TestCodeBlock:
    def test_known_language_preserved(self) -> None:
        from app.tools.notion_mcp import _code_block

        blocks = _code_block("print('hi')", "python")
        assert len(blocks) == 1
        assert blocks[0]["code"]["language"] == "python"

    def test_unknown_language_falls_back_to_plain_text(self) -> None:
        from app.tools.notion_mcp import _code_block

        blocks = _code_block("code here", "foobar")
        assert blocks[0]["code"]["language"] == "plain text"

    def test_language_normalised_to_lowercase(self) -> None:
        from app.tools.notion_mcp import _code_block

        blocks = _code_block("x = 1", "Python")
        assert blocks[0]["code"]["language"] == "python"

    def test_empty_code_produces_one_block(self) -> None:
        from app.tools.notion_mcp import _code_block

        blocks = _code_block("", "python")
        assert len(blocks) == 1


class TestNormalisePageId:
    def test_32_char_hex_is_formatted_as_uuid(self) -> None:
        from app.tools.notion_mcp import _normalise_page_id

        raw = "a" * 32
        result = _normalise_page_id(raw)
        assert result == "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"

    def test_already_dashed_uuid_is_returned_as_is(self) -> None:
        from app.tools.notion_mcp import _normalise_page_id

        uuid = "12345678-1234-1234-1234-123456789012"
        result = _normalise_page_id(uuid)
        assert result == uuid

    def test_dashed_uuid_is_normalised_correctly(self) -> None:
        from app.tools.notion_mcp import _normalise_page_id

        uuid_with_dashes = "12345678-1234-1234-1234-123456789012"
        result = _normalise_page_id(uuid_with_dashes)
        assert result == uuid_with_dashes

    def test_strips_surrounding_whitespace(self) -> None:
        from app.tools.notion_mcp import _normalise_page_id

        result = _normalise_page_id("  " + "b" * 32 + "  ")
        assert "-" in result
        assert result.replace("-", "") == "b" * 32


# ---------------------------------------------------------------------------
# markdown_to_notion_blocks
# ---------------------------------------------------------------------------


class TestMarkdownToNotionBlocks:
    def test_h1_produces_heading_1_block(self) -> None:
        from app.tools.notion_mcp import markdown_to_notion_blocks

        blocks = markdown_to_notion_blocks("# My Title")
        assert len(blocks) == 1
        assert blocks[0]["type"] == "heading_1"
        assert blocks[0]["heading_1"]["rich_text"][0]["text"]["content"] == "My Title"

    def test_h2_produces_heading_2_block(self) -> None:
        from app.tools.notion_mcp import markdown_to_notion_blocks

        blocks = markdown_to_notion_blocks("## Section")
        assert blocks[0]["type"] == "heading_2"

    def test_h3_produces_heading_3_block(self) -> None:
        from app.tools.notion_mcp import markdown_to_notion_blocks

        blocks = markdown_to_notion_blocks("### Sub")
        assert blocks[0]["type"] == "heading_3"

    def test_bullet_item_dash(self) -> None:
        from app.tools.notion_mcp import markdown_to_notion_blocks

        blocks = markdown_to_notion_blocks("- item one")
        assert blocks[0]["type"] == "bulleted_list_item"
        assert blocks[0]["bulleted_list_item"]["rich_text"][0]["text"]["content"] == "item one"

    def test_bullet_item_asterisk(self) -> None:
        from app.tools.notion_mcp import markdown_to_notion_blocks

        blocks = markdown_to_notion_blocks("* item two")
        assert blocks[0]["type"] == "bulleted_list_item"

    def test_ordered_list_item(self) -> None:
        from app.tools.notion_mcp import markdown_to_notion_blocks

        blocks = markdown_to_notion_blocks("1. First step")
        assert blocks[0]["type"] == "numbered_list_item"
        assert blocks[0]["numbered_list_item"]["rich_text"][0]["text"]["content"] == "First step"

    def test_divider(self) -> None:
        from app.tools.notion_mcp import markdown_to_notion_blocks

        blocks = markdown_to_notion_blocks("---")
        assert blocks[0]["type"] == "divider"

    def test_divider_triple_asterisk(self) -> None:
        from app.tools.notion_mcp import markdown_to_notion_blocks

        blocks = markdown_to_notion_blocks("***")
        assert blocks[0]["type"] == "divider"

    def test_paragraph(self) -> None:
        from app.tools.notion_mcp import markdown_to_notion_blocks

        blocks = markdown_to_notion_blocks("This is a paragraph.")
        assert blocks[0]["type"] == "paragraph"

    def test_empty_lines_are_skipped(self) -> None:
        from app.tools.notion_mcp import markdown_to_notion_blocks

        blocks = markdown_to_notion_blocks("\n\n\n")
        assert blocks == []

    def test_fenced_code_block(self) -> None:
        from app.tools.notion_mcp import markdown_to_notion_blocks

        md = "```python\nprint('hello')\n```"
        blocks = markdown_to_notion_blocks(md)
        assert len(blocks) == 1
        assert blocks[0]["type"] == "code"
        assert blocks[0]["code"]["language"] == "python"
        assert "print('hello')" in blocks[0]["code"]["rich_text"][0]["text"]["content"]

    def test_mixed_content(self) -> None:
        from app.tools.notion_mcp import markdown_to_notion_blocks

        md = "# Title\n\nSome paragraph.\n\n- bullet\n\n```bash\necho hi\n```"
        blocks = markdown_to_notion_blocks(md)
        types = [b["type"] for b in blocks]
        assert "heading_1" in types
        assert "paragraph" in types
        assert "bulleted_list_item" in types
        assert "code" in types

    def test_all_blocks_have_object_block(self) -> None:
        from app.tools.notion_mcp import markdown_to_notion_blocks

        md = "# H\n\npara\n\n- bullet\n\n1. numbered\n\n---\n\n```py\ncode\n```"
        blocks = markdown_to_notion_blocks(md)
        for block in blocks:
            assert block.get("object") == "block"


# ---------------------------------------------------------------------------
# extract_title_from_markdown
# ---------------------------------------------------------------------------


class TestExtractTitleFromMarkdown:
    def test_extracts_first_h1(self) -> None:
        from app.tools.notion_mcp import extract_title_from_markdown

        title = extract_title_from_markdown("# My Blog Post\n\nContent here.")
        assert title == "My Blog Post"

    def test_returns_default_when_no_h1(self) -> None:
        from app.tools.notion_mcp import extract_title_from_markdown

        title = extract_title_from_markdown("No heading here.")
        assert title == "Blog Post"

    def test_ignores_h2_and_h3(self) -> None:
        from app.tools.notion_mcp import extract_title_from_markdown

        title = extract_title_from_markdown("## Section\n### Sub\nNo H1.")
        assert title == "Blog Post"

    def test_trims_whitespace_from_title(self) -> None:
        from app.tools.notion_mcp import extract_title_from_markdown

        title = extract_title_from_markdown("#   Spaced Title   \n\nContent.")
        assert title == "Spaced Title"


# ---------------------------------------------------------------------------
# create_notion_page (mocked httpx)
# ---------------------------------------------------------------------------


class TestCreateNotionPage:
    @pytest.mark.asyncio
    async def test_creates_page_and_appends_blocks(self) -> None:
        from unittest.mock import AsyncMock, MagicMock, patch

        from app.tools.notion_mcp import create_notion_page

        mock_page_response = MagicMock()
        mock_page_response.json.return_value = {
            "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "url": "https://notion.so/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        }
        mock_page_response.raise_for_status = MagicMock()

        mock_patch_response = MagicMock()
        mock_patch_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_page_response)
        mock_client.patch = AsyncMock(return_value=mock_patch_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            url = await create_notion_page(
                token="secret_test",
                parent_page_id="b" * 32,
                title="Test Post",
                content="# Test Post\n\nHello world.",
            )

        assert "notion.so" in url
        mock_client.post.assert_called_once()
        # Blocks are appended via PATCH
        mock_client.patch.assert_called()

    @pytest.mark.asyncio
    async def test_raises_on_non_2xx_response(self) -> None:
        from unittest.mock import AsyncMock, MagicMock, patch

        from app.tools.notion_mcp import create_notion_page

        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "403 Forbidden",
            request=MagicMock(),
            response=MagicMock(status_code=403),
        )

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(httpx.HTTPStatusError):
                await create_notion_page(
                    token="bad_token",
                    parent_page_id="c" * 32,
                    title="Fail",
                    content="content",
                )

    @pytest.mark.asyncio
    async def test_large_content_is_batched(self) -> None:
        """More than 100 blocks should trigger multiple PATCH calls."""
        from unittest.mock import AsyncMock, MagicMock, patch

        from app.tools.notion_mcp import create_notion_page

        # 110 bullet items → 2 PATCH calls (100 + 10)
        content = "\n".join(f"- Item {i}" for i in range(110))

        mock_page_response = MagicMock()
        mock_page_response.json.return_value = {
            "id": "dddddddd-dddd-dddd-dddd-dddddddddddd",
            "url": "https://notion.so/dddddddddddddddddddddddddddddddd",
        }
        mock_page_response.raise_for_status = MagicMock()

        mock_patch_response = MagicMock()
        mock_patch_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_page_response)
        mock_client.patch = AsyncMock(return_value=mock_patch_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            await create_notion_page(
                token="secret_test",
                parent_page_id="d" * 32,
                title="Big Post",
                content=content,
            )

        assert mock_client.patch.call_count == 2
