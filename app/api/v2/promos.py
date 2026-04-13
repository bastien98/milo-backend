"""Weekly promo reports, search, and folder browsing endpoints."""

import logging
import os
import time
from datetime import date
from typing import List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_current_db_user
from app.core.stores import ALL_STORE_NAMES, STORE_DISPLAY_NAMES, STORE_HAS_PROMOS
from app.models.user import User
from app.schemas.promo import (
    PromoFolderHotspot,
    PromoFolderInfo,
    PromoFolderPage,
    PromoFoldersResponse,
    PromoRecommendationResponse,
    PromoReportEventCreate,
    PromoSearchRequest,
    PromoSearchResponse,
    PromoStoreOption,
)
from app.services.promo_report_service import PromoReportNotFoundError, PromoReportService
from app.services.promo_search_service import PromoSearchService

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get(
    "",
    response_model=PromoRecommendationResponse,
    responses={
        503: {"description": "Promo report service unavailable"},
    },
)
async def get_promo_recommendations(
    current_user: User = Depends(get_current_db_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the stored weekly promo report for the current user."""
    service = PromoReportService(db)

    try:
        recommendations = await service.get_current_report_response(current_user.id)
    except Exception as e:
        logger.error(f"Promo report lookup failed for user {current_user.id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not load promo report. Please try again later.",
        )

    return recommendations


@router.post(
    "/events",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def create_promo_report_event(
    payload: PromoReportEventCreate,
    current_user: User = Depends(get_current_db_user),
    db: AsyncSession = Depends(get_db),
):
    """Log a promo report interaction event for the current user."""
    service = PromoReportService(db)

    try:
        await service.log_event(
            user_id=current_user.id,
            report_id=payload.report_id,
            event_type=payload.event_type,
            item_key=payload.item_key,
            store_name=payload.store_name,
            metadata=payload.metadata,
        )
    except PromoReportNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Promo report not found.",
        )
    except Exception as e:
        logger.error(f"Promo report event logging failed for user {current_user.id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not log promo report event.",
        )

    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Promo Folders (browsable folder pages from R2)
# ---------------------------------------------------------------------------

# In-memory TTL cache: (data, timestamp)
_folders_cache: Optional[Tuple[PromoFoldersResponse, float]] = None
_FOLDERS_CACHE_TTL = 3600  # 1 hour

R2_PUBLIC_BASE_URL = os.environ.get("R2_PUBLIC_BASE_URL", "")


def _query_hotspots_by_retailer(today_str: str) -> dict[str, list[PromoFolderHotspot]]:
    """Query promo items with tile bounding boxes, grouped by (retailer, page_number).

    Returns a dict keyed by "{retailer}:{page_number}" → list of hotspots.
    """
    import psycopg2

    db_url = os.environ.get("DATABASE_URL", "")
    for suffix in ("+asyncpg", "+psycopg2"):
        db_url = db_url.replace(suffix, "")

    if not db_url:
        logger.warning("DATABASE_URL not set — no hotspots available")
        return {}

    try:
        conn = psycopg2.connect(db_url)
    except Exception as e:
        logger.warning(f"Failed to connect to DB for hotspots: {e}")
        return {}

    hotspots_map: dict[str, list[PromoFolderHotspot]] = {}
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
                id, source_retailer, page_number,
                tile_bbox_x_min, tile_bbox_y_min, tile_bbox_x_max, tile_bbox_y_max,
                display_name, display_brand, display_mechanism,
                original_price, promo_price, savings_amount, promo_depth,
                min_purchase_qty, validity_end,
                thumbnail_url, image_url
            FROM promo_items
            WHERE tile_bbox_x_min IS NOT NULL
              AND validity_end >= %s
              AND page_number IS NOT NULL
            """,
            (today_str,),
        )
        for row in cur.fetchall():
            (
                item_id, retailer, page_number,
                tx_min, ty_min, tx_max, ty_max,
                display_name, display_brand, display_mechanism,
                original_price, promo_price, savings_amount, promo_depth,
                min_purchase_qty, validity_end,
                thumbnail_url, image_url,
            ) = row

            discount_pct = int(round(promo_depth)) if promo_depth else 0

            hotspot = PromoFolderHotspot(
                item_id=item_id,
                page_number=page_number,
                tile_bbox_x_min=tx_min,
                tile_bbox_y_min=ty_min,
                tile_bbox_x_max=tx_max,
                tile_bbox_y_max=ty_max,
                display_name=display_name,
                display_brand=display_brand,
                display_mechanism=display_mechanism or "",
                original_price=original_price,
                promo_price=promo_price,
                savings_amount=savings_amount,
                discount_percentage=discount_pct,
                min_purchase_qty=min_purchase_qty or 1,
                validity_end=str(validity_end),
                thumbnail_url=thumbnail_url,
                image_url=image_url,
                store_name=retailer,
            )
            key = f"{retailer}:{page_number}"
            hotspots_map.setdefault(key, []).append(hotspot)

        cur.close()
    except Exception as e:
        logger.warning(f"Failed to query hotspots: {e}")
    finally:
        conn.close()

    return hotspots_map


def _build_folders_response() -> PromoFoldersResponse:
    """Read R2 metadata and build the folders response.

    Lists all active promo folders across all configured retailers,
    constructing page image URLs from the R2 public base URL.
    Attaches promo item hotspots (with tile bounding boxes) to each page.
    """
    from promo_folders_pipelines.scraper.config import RETAILERS
    from promo_folders_pipelines.r2_storage import R2PromoStorage, R2_BUCKET, R2_PREFIX

    if not R2_PUBLIC_BASE_URL:
        logger.warning("R2_PUBLIC_BASE_URL not set — returning empty folders")
        return PromoFoldersResponse(folders=[])

    r2 = R2PromoStorage()
    today = date.today().isoformat()

    # Query all hotspots once (single DB call)
    hotspots_map = _query_hotspots_by_retailer(today)

    folders: list[PromoFolderInfo] = []

    for _key, retailer in RETAILERS.items():
        store_id = retailer["store_id"]
        safe_id = store_id.replace(" ", "_")
        prefix = f"{R2_PREFIX}{safe_id}/"

        # List folder sub-directories (folder_1/, folder_2/, etc.)
        try:
            response = r2.client.list_objects_v2(
                Bucket=R2_BUCKET, Prefix=prefix, Delimiter="/"
            )
        except Exception as e:
            logger.warning(f"Failed to list R2 prefix {prefix}: {e}")
            continue

        for cp in response.get("CommonPrefixes", []):
            folder_prefix = cp["Prefix"]  # e.g., "promo_folders/colruyt/folder_1/"
            folder_dir = folder_prefix.rstrip("/").rsplit("/", 1)[-1]  # "folder_1"

            # Download metadata.json
            meta_key = f"{folder_prefix}metadata.json"
            try:
                meta_response = r2.client.get_object(Bucket=R2_BUCKET, Key=meta_key)
                import json
                metadata = json.loads(meta_response["Body"].read())
            except Exception as e:
                logger.debug(f"No metadata at {meta_key}: {e}")
                continue

            # Filter: only active folders (validity_end >= today)
            validity_end = metadata.get("validity_end", "")
            if validity_end and validity_end < today:
                continue

            page_count = metadata.get("page_count", 0)
            if page_count == 0:
                continue

            # Build page image URLs with hotspots
            pages = [
                PromoFolderPage(
                    page_number=i,
                    image_url=f"{R2_PUBLIC_BASE_URL}/{R2_PREFIX}{safe_id}/{folder_dir}/page_{i:03d}.webp",
                    hotspots=hotspots_map.get(f"{store_id}:{i}", []),
                )
                for i in range(1, page_count + 1)
            ]

            display_name = STORE_DISPLAY_NAMES.get(store_id, store_id.title())

            folders.append(PromoFolderInfo(
                folder_id=f"{safe_id}/{folder_dir}",
                store_id=store_id,
                store_display_name=display_name,
                folder_name=metadata.get("folder_name", folder_dir.replace("_", " ").title()),
                source_url=metadata.get("source_url", ""),
                validity_start=metadata.get("validity_start", ""),
                validity_end=validity_end,
                page_count=page_count,
                pages=pages,
            ))

    # Sort: by store_id, then folder_id
    folders.sort(key=lambda f: (f.store_id, f.folder_id))
    return PromoFoldersResponse(folders=folders)


@router.get("/folders", response_model=PromoFoldersResponse)
async def get_promo_folders():
    """Return all active promo folders with page image URLs, grouped by store.

    Public endpoint — no authentication required.
    Results are cached in memory for 1 hour.
    """
    global _folders_cache

    now = time.time()
    if _folders_cache is not None:
        data, cached_at = _folders_cache
        if now - cached_at < _FOLDERS_CACHE_TTL:
            return data

    try:
        data = _build_folders_response()
        _folders_cache = (data, now)
        return data
    except Exception as e:
        logger.error(f"Failed to build promo folders response: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Promo folders are temporarily unavailable.",
        )


# ---------------------------------------------------------------------------
# Promo Search
# ---------------------------------------------------------------------------


@router.get("/stores", response_model=List[PromoStoreOption])
async def get_promo_stores():
    """Return all stores available for promo search filtering."""
    return [
        PromoStoreOption(
            id=name,
            name=STORE_DISPLAY_NAMES[name],
            has_promos=STORE_HAS_PROMOS.get(name, False),
        )
        for name in ALL_STORE_NAMES
        if name != "other"
    ]


@router.post("/search", response_model=PromoSearchResponse)
async def search_promos(
    payload: PromoSearchRequest,
    current_user: User = Depends(get_current_db_user),
):
    """Search current promos by product name/description and store filters."""
    service = PromoSearchService()

    try:
        results = await service.search(payload.query, payload.stores)
    except Exception as e:
        logger.error(
            f"Promo search failed for user {current_user.id}: {e}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Promo search is temporarily unavailable. Please try again later.",
        )

    return PromoSearchResponse(
        query=payload.query,
        stores=payload.stores,
        result_count=len(results),
        results=results,
    )
