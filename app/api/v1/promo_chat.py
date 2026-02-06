"""
Promo Chat API Endpoint

Allows users to search for grocery promotions using natural language.
The LLM extracts structured search parameters and queries the Pinecone promos index.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_current_db_user
from app.config import get_settings
from app.models.user import User
from app.schemas.promo_chat import PromoChatRequest, PromoChatResponse
from app.services.promo_chat_service import PromoChatService
from app.services.rate_limit_service import RateLimitService
from app.core.exceptions import RateLimitExceededError

router = APIRouter()
logger = logging.getLogger(__name__)
settings = get_settings()


def build_rate_limit_headers(status, account_for_current: bool = True) -> dict:
    """Build rate limit response headers."""
    reset_timestamp = int(status.period_end_date.timestamp())
    remaining = status.messages_remaining
    if account_for_current and remaining > 0:
        remaining -= 1
    return {
        "X-RateLimit-Limit": str(status.messages_limit),
        "X-RateLimit-Remaining": str(remaining),
        "X-RateLimit-Reset": str(reset_timestamp),
    }


@router.post("/", response_model=PromoChatResponse)
async def promo_chat(
    request: PromoChatRequest,
    response: Response,
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

    Rate limit information is included in the response headers:
    - X-RateLimit-Limit: Maximum messages allowed per period
    - X-RateLimit-Remaining: Messages remaining in current period
    - X-RateLimit-Reset: Unix timestamp when the rate limit resets
    """
    # Check rate limit
    rate_limit_service = RateLimitService(db)
    rate_status = await rate_limit_service.check_rate_limit(current_user.firebase_uid)

    if not rate_status.allowed:
        raise RateLimitExceededError(
            message="You've reached your message limit for this period",
            details={
                "messages_used": rate_status.messages_used,
                "messages_limit": rate_status.messages_limit,
                "period_end_date": rate_status.period_end_date.isoformat(),
                "retry_after_seconds": rate_status.retry_after_seconds,
            },
        )

    try:
        promo_service = PromoChatService()
        result = await promo_service.chat(
            message=request.message,
            conversation_history=request.conversation_history,
        )

        # Increment counter on successful response
        await rate_status.increment_on_success()

        # Add rate limit headers
        rate_headers = build_rate_limit_headers(rate_status)
        for key, value in rate_headers.items():
            response.headers[key] = value

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
