"""
Promo Chat API Endpoint

Allows users to search for grocery promotions using natural language.
The LLM extracts structured search parameters and queries the Pinecone promos index.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_current_db_user
from app.config import get_settings
from app.models.user import User
from app.models.user_profile import UserProfile
from app.schemas.promo_chat import PromoChatRequest, PromoChatResponse
from app.services.promo_chat_service import PromoChatService

router = APIRouter()
logger = logging.getLogger(__name__)
settings = get_settings()


@router.post("/", response_model=PromoChatResponse)
async def promo_chat(
    request: PromoChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
):
    """
    Search for grocery promotions using natural language.

    The AI extracts your search intent and finds matching promotions
    from Belgian supermarkets (Colruyt, Delhaize, Carrefour, Aldi, Lidl, etc.).

    Examples:
    - "Any coffee deals this week?"
    - "What's on sale at Colruyt?"
    - "Jupiler beer promotions"
    - "Cheap diapers"

    If your query is too vague, the AI will ask for clarification.
    """
    # Fetch user's language preference
    profile_result = await db.execute(
        select(UserProfile.language).where(UserProfile.user_id == current_user.firebase_uid)
    )
    user_language = profile_result.scalar_one_or_none()

    try:
        promo_service = PromoChatService()
        result = await promo_service.chat(
            message=request.message,
            conversation_history=request.conversation_history,
            language=user_language,
        )

        return result

    except Exception as e:
        logger.exception(f"Promo chat error: {e}")
        raise HTTPException(status_code=500, detail="Failed to process promo search request")


# Debug/Test endpoint - only available when DEBUG=True
@router.post("/test", response_model=PromoChatResponse, include_in_schema=False)
async def promo_chat_test(
    request: PromoChatRequest,
    db: AsyncSession = Depends(get_db),
    user_email: Optional[str] = Query(None, description="Email of user to test as"),
):
    """
    Test endpoint for promo chat - only available in DEBUG mode.
    Allows testing without authentication.
    """
    if not settings.DEBUG:
        raise HTTPException(status_code=404, detail="Not found")

    # Get first user or user by email
    if user_email:
        result = await db.execute(
            select(User).where(User.email == user_email)
        )
    else:
        result = await db.execute(select(User).limit(1))

    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="No users found in database")

    try:
        promo_service = PromoChatService()
        return await promo_service.chat(
            message=request.message,
            conversation_history=request.conversation_history,
        )
    except Exception as e:
        logger.exception(f"Promo chat test error: {e}")
        raise HTTPException(status_code=500, detail="Failed to process promo search request")
