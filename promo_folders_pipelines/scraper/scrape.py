"""Core scraper for promopromo.be promo folders.

Fetches retailer listing pages, parses Nuxt SSR payloads to extract
folder metadata and page image URLs, and downloads images.
"""

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime

import httpx
from bs4 import BeautifulSoup

from .config import PROMOPROMO_BASE

logger = logging.getLogger(__name__)

# Timeout for HTTP requests (seconds)
HTTP_TIMEOUT = 30.0
# Max concurrent image downloads
MAX_CONCURRENT_DOWNLOADS = 10


@dataclass
class FolderInfo:
    """Metadata for a single promo folder discovered on promopromo.be."""
    uuid: str
    name: str
    active_from: str  # ISO 8601
    expire_after: str  # ISO 8601
    shop_slug: str

    @property
    def validity_start(self) -> str:
        """Return validity start as YYYY-MM-DD."""
        return datetime.fromisoformat(self.active_from).strftime("%Y-%m-%d")

    @property
    def validity_end(self) -> str:
        """Return validity end as YYYY-MM-DD."""
        return datetime.fromisoformat(self.expire_after).strftime("%Y-%m-%d")


@dataclass
class FolderPages:
    """All page image URLs for a folder."""
    folder: FolderInfo
    pages: list[dict] = field(default_factory=list)  # [{"index": 0, "url": "...", "page_uuid": "..."}]

    @property
    def page_count(self) -> int:
        return len(self.pages)


def _parse_nuxt_data(html: str) -> list:
    """Extract the __NUXT_DATA__ JSON array from HTML."""
    soup = BeautifulSoup(html, "html.parser")
    script = soup.find("script", id="__NUXT_DATA__")
    if not script or not script.string:
        raise ValueError("Could not find __NUXT_DATA__ script tag in HTML")
    return json.loads(script.string)


def _extract_urql_queries(nuxt_array: list) -> list[dict]:
    """Extract all URQL cached query results from the Nuxt hydration array.

    The Nuxt array is a flat array where objects reference other elements by index.
    URQL data is stored as double-encoded JSON strings that need a second parse.
    """
    results = []

    # Walk through the array looking for JSON strings that contain GraphQL data
    for item in nuxt_array:
        if not isinstance(item, str):
            continue
        # Try to parse strings that look like JSON objects
        if not item.startswith("{"):
            continue
        try:
            parsed = json.loads(item)
            if isinstance(parsed, dict):
                results.append(parsed)
        except (json.JSONDecodeError, ValueError):
            continue

    return results


def discover_folders(shop_slug: str, shop_uuid: str) -> list[FolderInfo]:
    """Fetch the shop listing page and extract all active folder metadata.

    Args:
        shop_slug: promopromo.be shop slug (e.g., "colruyt")
        shop_uuid: stable shop UUID on promopromo.be

    Returns:
        List of FolderInfo objects for all active folders.
    """
    url = (
        f"{PROMOPROMO_BASE}/nl/zoekresultaten/"
        f"{shop_slug.replace('-', '%20').title()}/shop/{shop_uuid}?q={shop_slug}"
    )
    logger.info(f"Fetching folder listing: {url}")

    with httpx.Client(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
        response = client.get(url)
        response.raise_for_status()

    nuxt_array = _parse_nuxt_data(response.text)
    queries = _extract_urql_queries(nuxt_array)

    folders = []
    for query_data in queries:
        # Look for the searchResults query
        search_results = query_data.get("searchResults")
        if not search_results:
            continue

        brochures = search_results.get("brochures", [])
        for b in brochures:
            shop = b.get("shop", {})
            folders.append(FolderInfo(
                uuid=b["id"],
                name=b.get("name", ""),
                active_from=b.get("activeFrom", ""),
                expire_after=b.get("expireAfter", ""),
                shop_slug=shop.get("slug", shop_slug),
            ))

    logger.info(f"Found {len(folders)} folder(s) for {shop_slug}")
    for f in folders:
        logger.info(f"  - {f.name} ({f.uuid}) valid {f.validity_start} to {f.validity_end}")

    return folders


def fetch_folder_pages(folder: FolderInfo) -> FolderPages:
    """Fetch a folder's detail page and extract all page image URLs.

    Args:
        folder: FolderInfo from discover_folders()

    Returns:
        FolderPages with all page image URLs (large size).
    """
    url = f"{PROMOPROMO_BASE}/nl/{folder.shop_slug}-folder/{folder.uuid}/0"
    logger.info(f"Fetching folder pages: {url}")

    with httpx.Client(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
        response = client.get(url)
        response.raise_for_status()

    nuxt_array = _parse_nuxt_data(response.text)
    queries = _extract_urql_queries(nuxt_array)

    pages = []
    for query_data in queries:
        # Look for the pages query (has a "pages" key with a list)
        page_list = query_data.get("pages")
        if not isinstance(page_list, list):
            continue

        for p in page_list:
            image_url = p.get("image_large") or p.get("fileUrl", "")
            if not image_url:
                # Try constructing from page UUID
                page_uuid = p.get("id", "")
                if page_uuid:
                    image_url = f"https://cdn.jafolders.com/pages/{page_uuid}/large.webp"

            pages.append({
                "index": p.get("index", len(pages)),
                "url": image_url,
                "page_uuid": p.get("id", ""),
            })

    # Sort by index
    pages.sort(key=lambda x: x["index"])

    result = FolderPages(folder=folder, pages=pages)
    logger.info(f"Found {result.page_count} page(s) for folder {folder.uuid}")
    return result


def download_page_images(folder_pages: FolderPages) -> list[tuple[int, bytes]]:
    """Download all page images for a folder.

    Returns:
        List of (page_number, image_bytes) tuples, 1-indexed.
    """
    results = []

    with httpx.Client(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
        for position, page in enumerate(folder_pages.pages, start=1):
            url = page["url"]
            page_num = position  # 1-indexed based on sorted order
            logger.info(
                f"Downloading page {page_num}/{folder_pages.page_count}: {url[:80]}..."
            )
            response = client.get(url)
            response.raise_for_status()
            results.append((page_num, response.content))

    logger.info(
        f"Downloaded {len(results)} page(s) "
        f"({sum(len(b) for _, b in results) / 1_000_000:.1f} MB total)"
    )
    return results
