"""
Unsplash image search for embedding images in blog post drafts.

Uses the Unsplash API (GET /search/photos) to find relevant images.
Results include attribution required by Unsplash's terms of service.
"""

import logging
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_UNSPLASH_API_BASE = "https://api.unsplash.com"


@dataclass(frozen=True)
class ImageResult:
    url: str
    description: str
    photographer: str
    source: str = "Unsplash"


async def search_unsplash_images(
    query: str,
    *,
    access_key: str,
    count: int = 3,
) -> list[ImageResult]:
    """Search Unsplash for images matching *query*.

    Parameters
    ----------
    query:
        Search term (e.g. "python programming", "cloud architecture").
    access_key:
        Unsplash API access key.
    count:
        Number of results to return (max 30).

    Returns
    -------
    list[ImageResult]
        Matching images with URLs and attribution.
    """
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"{_UNSPLASH_API_BASE}/search/photos",
            params={"query": query, "per_page": count, "orientation": "landscape"},
            headers={"Authorization": f"Client-ID {access_key}"},
        )
        resp.raise_for_status()

    data: dict[str, Any] = resp.json()
    results: list[ImageResult] = []
    for item in data.get("results", []):
        results.append(
            ImageResult(
                url=item["urls"]["regular"],
                description=item.get("alt_description") or "Image",
                photographer=item["user"]["name"],
            )
        )

    logger.info("Unsplash search '%s': %d results", query, len(results))
    return results
