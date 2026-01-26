import json
import logging
from typing import AsyncGenerator, Optional, Callable, Awaitable

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_current_db_user
from app.config import get_settings
from app.db.session import async_session_maker
from app.models.user import User
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.dobby_chat_service_gemini import DobbyChatServiceGemini
from app.services.rate_limit_service import RateLimitService, RateLimitStatus
from app.core.exceptions import GeminiAPIError, RateLimitExceededError

router = APIRouter()
logger = logging.getLogger(__name__)
settings = get_settings()


def build_rate_limit_headers(status: RateLimitStatus, account_for_current: bool = True) -> dict:
    """
    Build rate limit response headers.

    Args:
        status: The current rate limit status
        account_for_current: If True, remaining count reflects this request being processed
                           (i.e., remaining = original remaining - 1)
    """
    reset_timestamp = int(status.period_end_date.timestamp())
    remaining = status.messages_remaining
    if account_for_current and remaining > 0:
        remaining -= 1
    return {
        "X-RateLimit-Limit": str(status.messages_limit),
        "X-RateLimit-Remaining": str(remaining),
        "X-RateLimit-Reset": str(reset_timestamp),
    }


@router.post("/", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
):
    """
    Send a message to Dobby AI and receive a response about your transactional data.

    This is a non-streaming endpoint that returns the complete response at once.
    Uses Google Gemini for AI processing.

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
        chat_service = DobbyChatServiceGemini()
        response_text = await chat_service.chat(
            db=db,
            user_id=str(current_user.id),
            message=request.message,
            conversation_history=request.conversation_history,
        )

        # Increment counter on successful response
        await rate_status.increment_on_success()

        # Add rate limit headers to response
        rate_headers = build_rate_limit_headers(rate_status)
        for key, value in rate_headers.items():
            response.headers[key] = value

        return ChatResponse(response=response_text)
    except GeminiAPIError:
        raise
    except Exception as e:
        logger.exception(f"Chat error: {e}")
        raise HTTPException(status_code=500, detail="Failed to process chat request")


async def stream_response(
    user_id: str,
    message: str,
    conversation_history,
    firebase_uid: str,
) -> AsyncGenerator[str, None]:
    """
    Generate Server-Sent Events for streaming chat response.

    IMPORTANT: This function manages its own database session because FastAPI's
    dependency injection lifecycle ends when StreamingResponse is returned,
    not when the stream completes. Managing the session here prevents connection leaks.
    """
    async with async_session_maker() as db:
        try:
            # Check and increment rate limit within our own session
            rate_limit_service = RateLimitService(db)
            rate_status = await rate_limit_service.check_rate_limit(firebase_uid)

            chat_service = DobbyChatServiceGemini()
            async for chunk in chat_service.chat_stream(
                db=db,
                user_id=user_id,
                message=message,
                conversation_history=conversation_history,
            ):
                # Format as SSE data event
                data = json.dumps({"type": "text", "content": chunk})
                yield f"data: {data}\n\n"

            # Increment rate limit counter on successful completion
            await rate_status.increment_on_success()
            await db.commit()

            # Send done event
            yield f"data: {json.dumps({'type': 'done'})}\n\n"

        except GeminiAPIError as e:
            error_data = json.dumps({"type": "error", "error": str(e.message)})
            yield f"data: {error_data}\n\n"
        except Exception as e:
            logger.exception(f"Streaming chat error: {e}")
            error_data = json.dumps({"type": "error", "error": "Failed to process chat request"})
            yield f"data: {error_data}\n\n"


@router.post("/stream")
async def chat_stream(
    request: ChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
):
    """
    Send a message to Dobby AI and receive a streaming response about your transactional data.

    This endpoint uses Server-Sent Events (SSE) to stream the response.
    Uses Google Gemini for AI processing.

    Each event is a JSON object with:
    - type: "text" | "error" | "done"
    - content: The text chunk (for "text" type)
    - error: The error message (for "error" type)

    Rate limit information is included in the response headers:
    - X-RateLimit-Limit: Maximum messages allowed per period
    - X-RateLimit-Remaining: Messages remaining in current period
    - X-RateLimit-Reset: Unix timestamp when the rate limit resets
    """
    # Check rate limit (initial check only - actual increment happens in stream_response)
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

    # Build headers with rate limit info
    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",  # Disable nginx buffering
        **build_rate_limit_headers(rate_status),
    }

    # NOTE: stream_response manages its own database session because FastAPI's
    # dependency injection lifecycle ends when StreamingResponse is returned,
    # not when the stream completes. This prevents connection pool exhaustion.
    return StreamingResponse(
        stream_response(
            user_id=str(current_user.id),
            message=request.message,
            conversation_history=request.conversation_history,
            firebase_uid=current_user.firebase_uid,
        ),
        media_type="text/event-stream",
        headers=headers,
    )


# Debug/Test endpoints - only available when DEBUG=True
@router.post("/test", response_model=ChatResponse, include_in_schema=False)
async def chat_test(
    request: ChatRequest,
    db: AsyncSession = Depends(get_db),
    user_email: Optional[str] = Query(None, description="Email of user to test as"),
):
    """
    Test endpoint for chat - only available in DEBUG mode.
    Allows testing without authentication by specifying a user email.
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
        chat_service = DobbyChatServiceGemini()
        response_text = await chat_service.chat(
            db=db,
            user_id=str(user.id),
            message=request.message,
            conversation_history=request.conversation_history,
        )
        return ChatResponse(response=response_text)
    except GeminiAPIError:
        raise
    except Exception as e:
        logger.exception(f"Chat test error: {e}")
        raise HTTPException(status_code=500, detail="Failed to process chat request")


@router.post("/test/stream", include_in_schema=False)
async def chat_test_stream(
    request: ChatRequest,
    db: AsyncSession = Depends(get_db),
    user_email: Optional[str] = Query(None, description="Email of user to test as"),
):
    """
    Test endpoint for streaming chat - only available in DEBUG mode.
    Allows testing without authentication by specifying a user email.
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

    # NOTE: stream_response manages its own database session
    return StreamingResponse(
        stream_response(
            user_id=str(user.id),
            message=request.message,
            conversation_history=request.conversation_history,
            firebase_uid=user.firebase_uid,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
