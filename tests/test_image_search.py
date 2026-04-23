"""
Tests for app/tools/image_search.py — Unsplash image search tool.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.tools.image_search import ImageResult, search_unsplash_images


class TestImageResult:
    def test_frozen_dataclass(self) -> None:
        result = ImageResult(
            url="https://images.unsplash.com/photo-123",
            description="A sunset",
            photographer="Jane Doe",
        )
        assert result.url == "https://images.unsplash.com/photo-123"
        assert result.source == "Unsplash"
        with pytest.raises(AttributeError):
            result.url = "changed"  # type: ignore[misc]


class TestSearchUnsplashImages:
    @pytest.mark.asyncio
    async def test_returns_image_results(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "results": [
                {
                    "urls": {"regular": "https://images.unsplash.com/photo-1"},
                    "alt_description": "a mountain landscape",
                    "user": {"name": "John Doe"},
                },
                {
                    "urls": {"regular": "https://images.unsplash.com/photo-2"},
                    "alt_description": "ocean view",
                    "user": {"name": "Jane Smith"},
                },
            ]
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            results = await search_unsplash_images("mountain", access_key="test-key", count=2)

        assert len(results) == 2
        assert results[0].url == "https://images.unsplash.com/photo-1"
        assert results[0].description == "a mountain landscape"
        assert results[0].photographer == "John Doe"
        assert results[0].source == "Unsplash"

    @pytest.mark.asyncio
    async def test_count_parameter_passed_to_api(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"results": []}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            await search_unsplash_images("test", access_key="key", count=5)

        call_kwargs = mock_client.get.call_args
        assert call_kwargs[1]["params"]["per_page"] == 5

    @pytest.mark.asyncio
    async def test_handles_missing_alt_description(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "results": [
                {
                    "urls": {"regular": "https://images.unsplash.com/photo-1"},
                    "alt_description": None,
                    "user": {"name": "Photographer"},
                },
            ]
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            results = await search_unsplash_images("test", access_key="key")

        assert results[0].description == "Image"

    @pytest.mark.asyncio
    async def test_raises_on_api_error(self) -> None:
        import httpx

        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "401 Unauthorized",
            request=MagicMock(),
            response=MagicMock(status_code=401),
        )

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(httpx.HTTPStatusError):
                await search_unsplash_images("test", access_key="bad-key")

    @pytest.mark.asyncio
    async def test_empty_results(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"results": []}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            results = await search_unsplash_images("xyznonexistent", access_key="key")

        assert results == []
