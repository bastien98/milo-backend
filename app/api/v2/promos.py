"""Weekly promo reports and search endpoints."""

import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_current_db_user
from app.core.stores import ALL_STORE_NAMES, STORE_DISPLAY_NAMES
from app.models.user import User
from app.schemas.promo import (
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
# Promo Search
# ---------------------------------------------------------------------------


@router.get("/stores", response_model=List[PromoStoreOption])
async def get_promo_stores():
    """Return all stores available for promo search filtering."""
    return [
        PromoStoreOption(id=name, name=STORE_DISPLAY_NAMES[name])
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
