"""Promo recommendations endpoint.

Returns personalized weekly promo deals based on the user's enriched
shopping profile and live Pinecone promo index.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_current_db_user
from app.models.user import User
from app.schemas.promo import PromoRecommendationResponse
from app.services.promo_service import PromoService, ProfileNotFoundError, GeminiPromoError

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get(
    "",
    response_model=PromoRecommendationResponse,
    responses={
        404: {"description": "No enriched profile found for this user"},
        503: {"description": "AI recommendation service unavailable"},
    },
)
async def get_promo_recommendations(
    current_user: User = Depends(get_current_db_user),
    db: AsyncSession = Depends(get_db),
):
    """Get personalized promo recommendations for the current user.

    Searches live promotional data and generates AI-powered
    recommendations based on the user's shopping habits.
    """
    service = PromoService(db)

    try:
        recommendations = await service.get_recommendations(current_user.id)
    except ProfileNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "no_enriched_profile",
                "message": "No enriched profile found. Scan more receipts to unlock promo recommendations.",
            },
        )
    except GeminiPromoError as e:
        logger.error(f"Gemini promo generation failed for user {current_user.id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "ai_service_unavailable",
                "message": "Promo recommendation service is temporarily unavailable. Please try again later.",
            },
        )
    except Exception as e:
        logger.error(f"Promo recommendation failed for user {current_user.id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "service_error",
                "message": "Could not generate promo recommendations. Please try again later.",
            },
        )

    return recommendations
