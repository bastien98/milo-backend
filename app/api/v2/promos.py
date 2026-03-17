"""Weekly promo reports endpoint."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_current_db_user
from app.models.user import User
from app.schemas.promo import PromoRecommendationResponse, PromoReportEventCreate
from app.services.promo_report_service import PromoReportNotFoundError, PromoReportService

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
