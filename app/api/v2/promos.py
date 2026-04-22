"""Promo folder browsing, similar-promo recommendations, and interaction telemetry."""

import logging
import os
import time
from datetime import date, datetime, timezone
from typing import Optional, Tuple

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_optional_db_user
from app.core.stores import STORE_DISPLAY_NAMES
from app.db.repositories.enriched_profile_repo import EnrichedProfileRepository
from app.db.repositories.promo_interaction_event_repo import (
    PromoInteractionEventRepository,
)
from app.models.user import User
from app.schemas.promo import (
    PromoFolderHotspot,
    PromoFolderInfo,
    PromoFolderPage,
    PromoFoldersResponse,
    PromoInteractionEventCreate,
    PromoStoreItem,
    SimilarPromosResponse,
    SimilarPromosSource,
)
from app.services.promo_similarity_service import (
    PromoNotFoundError,
    PromoSimilarityService,
)

logger = logging.getLogger(__name__)

router = APIRouter()

R2_PUBLIC_BASE_URL = os.environ.get("R2_PUBLIC_BASE_URL", "")

# ---------------------------------------------------------------------------
# Similar Promos
# ---------------------------------------------------------------------------


@router.get(
    "/{promo_id}/similar",
    response_model=SimilarPromosResponse,
    responses={404: {"description": "Promo not found"}},
)
async def get_similar_promos(
    promo_id: str,
    limit: int = Query(10, ge=1, le=30),
    personalize: bool = Query(True),
    current_user: Optional[User] = Depends(get_optional_db_user),
    db: AsyncSession = Depends(get_db),
):
    """Return promos similar to the given source promo.

    Public endpoint. If a valid bearer token is provided AND personalize=true,
    the user's category profile is used as a within-tier re-ranker (it cannot
    promote a less-relevant item above a more-relevant one — content tier
    is always the primary sort key).
    """
    service = PromoSimilarityService(db)

    category_profiles: Optional[dict] = None
    if personalize and current_user is not None:
        try:
            profile = await EnrichedProfileRepository(db).get_by_user_id(current_user.id)
            if profile and profile.category_profiles:
                category_profiles = profile.category_profiles
        except Exception as e:
            logger.warning(f"Failed loading enriched profile for personalization: {e}")

    try:
        source_dict, items = await service.find_similar(
            source_id=promo_id,
            limit=limit,
            category_profiles=category_profiles,
        )
    except PromoNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Promo not found")

    return SimilarPromosResponse(
        source=SimilarPromosSource(**source_dict),
        items=[PromoStoreItem(**item) for item in items],
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


# ---------------------------------------------------------------------------
# Promo Interaction Events (telemetry)
# ---------------------------------------------------------------------------


@router.post(
    "/interactions",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def create_promo_interaction_event(
    payload: PromoInteractionEventCreate,
    current_user: Optional[User] = Depends(get_optional_db_user),
    db: AsyncSession = Depends(get_db),
):
    """Log a folder/carousel interaction. Accepts both authenticated and
    anonymous calls — anonymous events have user_id=NULL, still useful
    for aggregate CTR analysis.
    """
    repo = PromoInteractionEventRepository(db)
    try:
        await repo.create(
            event_type=payload.event_type,
            user_id=current_user.id if current_user else None,
            promo_item_id=payload.promo_item_id,
            source_item_id=payload.source_item_id,
            store_name=payload.store_name,
            metadata_json=payload.metadata,
        )
    except Exception as e:
        logger.error(f"Failed to log promo interaction event: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not log interaction event.",
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Promo Folders (browsable folder pages from R2)
# ---------------------------------------------------------------------------

# In-memory TTL cache: (data, timestamp)
_folders_cache: Optional[Tuple[PromoFoldersResponse, float]] = None
_FOLDERS_CACHE_TTL = 3600  # 1 hour


def _query_hotspots_by_folder_url(today_str: str) -> dict[str, list[PromoFolderHotspot]]:
    """Query promo items with tile bounding boxes, grouped by (promo_folder_url, page_number).

    Returns a dict keyed by "{promo_folder_url}:{page_number}" → list of hotspots.
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
                id, source_retailer, page_number, promo_folder_url,
                tile_bbox_x_min, tile_bbox_y_min, tile_bbox_x_max, tile_bbox_y_max,
                display_name, primary_brand, display_brand, display_mechanism,
                original_price, promo_price, savings_amount, promo_depth,
                min_purchase_qty, validity_end,
                thumbnail_url, image_url, hero_url,
                mechanism_kind, promo_campaign,
                promo_text_markdown
            FROM promo_items
            WHERE tile_bbox_x_min IS NOT NULL
              AND validity_end >= %s
              AND page_number IS NOT NULL
            """,
            (today_str,),
        )
        for row in cur.fetchall():
            (
                item_id, retailer, page_number, promo_folder_url,
                tx_min, ty_min, tx_max, ty_max,
                display_name, primary_brand, display_brand, display_mechanism,
                original_price, promo_price, savings_amount, promo_depth,
                min_purchase_qty, validity_end,
                thumbnail_url, image_url, hero_url,
                mechanism_kind, promo_campaign,
                promo_text_markdown,
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
                display_brand=primary_brand or display_brand,
                display_mechanism=display_mechanism or "",
                original_price=original_price,
                promo_price=promo_price,
                savings_amount=savings_amount or 0.0,
                discount_percentage=discount_pct,
                min_purchase_qty=min_purchase_qty or 1,
                validity_end=str(validity_end),
                thumbnail_url=thumbnail_url,
                image_url=image_url,
                hero_url=hero_url,
                store_name=retailer,
                price_unavailable=(float(promo_price or 0) == 0.0 and float(original_price or 0) == 0.0),
                mechanism_kind=mechanism_kind,
                promo_campaign=promo_campaign,
                promo_text_markdown=promo_text_markdown,
            )
            key = f"{promo_folder_url}:{page_number}"
            hotspots_map.setdefault(key, []).append(hotspot)

        cur.close()
    except Exception as e:
        logger.warning(f"Failed to query hotspots: {e}")
    finally:
        conn.close()

    return hotspots_map


def _build_folders_response() -> PromoFoldersResponse:
    """Read R2 metadata and build the folders response."""
    from promo_folders_pipelines.scraper.config import RETAILERS
    from promo_folders_pipelines.r2_storage import R2PromoStorage, R2_BUCKET, R2_PREFIX

    if not R2_PUBLIC_BASE_URL:
        logger.warning("R2_PUBLIC_BASE_URL not set — returning empty folders")
        return PromoFoldersResponse(folders=[])

    r2 = R2PromoStorage()
    today = date.today().isoformat()

    hotspots_map = _query_hotspots_by_folder_url(today)

    folders: list[PromoFolderInfo] = []

    for _key, retailer in RETAILERS.items():
        store_id = retailer["store_id"]
        safe_id = store_id.replace(" ", "_")
        prefix = f"{R2_PREFIX}{safe_id}/"

        try:
            response = r2.client.list_objects_v2(
                Bucket=R2_BUCKET, Prefix=prefix, Delimiter="/"
            )
        except Exception as e:
            logger.warning(f"Failed to list R2 prefix {prefix}: {e}")
            continue

        for cp in response.get("CommonPrefixes", []):
            folder_prefix = cp["Prefix"]
            folder_dir = folder_prefix.rstrip("/").rsplit("/", 1)[-1]

            meta_key = f"{folder_prefix}metadata.json"
            try:
                meta_response = r2.client.get_object(Bucket=R2_BUCKET, Key=meta_key)
                import json
                metadata = json.loads(meta_response["Body"].read())
            except Exception as e:
                logger.debug(f"No metadata at {meta_key}: {e}")
                continue

            validity_end = metadata.get("validity_end", "")
            if validity_end and validity_end < today:
                continue

            page_count = metadata.get("page_count", 0)
            if page_count == 0:
                continue

            folder_source_url = metadata.get("source_url", "")

            pages = [
                PromoFolderPage(
                    page_number=i,
                    image_url=f"{R2_PUBLIC_BASE_URL}/{R2_PREFIX}{safe_id}/{folder_dir}/page_{i:03d}.webp",
                    hotspots=hotspots_map.get(f"{folder_source_url}:{i}", []) if folder_source_url else [],
                )
                for i in range(1, page_count + 1)
            ]

            display_name = STORE_DISPLAY_NAMES.get(store_id, store_id.title())

            folders.append(PromoFolderInfo(
                folder_id=f"{safe_id}/{folder_dir}",
                store_id=store_id,
                store_display_name=display_name,
                folder_name=metadata.get("folder_name", folder_dir.replace("_", " ").title()),
                source_url=folder_source_url,
                validity_start=metadata.get("validity_start", ""),
                validity_end=validity_end,
                page_count=page_count,
                pages=pages,
            ))

    folders.sort(key=lambda f: (f.store_id, f.folder_id))
    return PromoFoldersResponse(folders=folders)


@router.get("/folders", response_model=PromoFoldersResponse)
async def get_promo_folders():
    """Return all active promo folders with page image URLs, grouped by store.

    Public endpoint. Cached in memory for 1 hour.
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


@router.post("/folders/refresh", status_code=status.HTTP_204_NO_CONTENT)
async def refresh_promo_folders(
    x_refresh_token: Optional[str] = Header(None, alias="X-Refresh-Token"),
):
    """Invalidate the in-memory folders cache.

    Called by the ingest pipeline after a successful ingestion so newly-added
    hotspots surface on the next `/folders` request instead of waiting up to an
    hour for the TTL to expire. Protected by a shared secret — the server must
    have `PROMO_FOLDERS_REFRESH_TOKEN` set for this endpoint to accept calls.
    """
    global _folders_cache

    expected = os.environ.get("PROMO_FOLDERS_REFRESH_TOKEN", "")
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Folders refresh is not configured on this deployment.",
        )
    if not x_refresh_token or x_refresh_token != expected:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    _folders_cache = None
    logger.info("Promo folders cache invalidated via /folders/refresh")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
