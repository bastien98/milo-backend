import json
import logging
from typing import AsyncGenerator, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_current_db_user
from app.config import get_settings
from app.models.user import User
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.dobby_chat_service import DobbyChatService
from app.core.exceptions import ClaudeAPIError

router = APIRouter()
logger = logging.getLogger(__name__)
settings = get_settings()


@router.post("/", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
):
    """
    Send a message to Dobby AI and receive a response about your transactional data.

    This is a non-streaming endpoint that returns the complete response at once.
    """
    try:
        chat_service = DobbyChatService()
        response_text = await chat_service.chat(
            db=db,
            user_id=str(current_user.id),
            message=request.message,
            conversation_history=request.conversation_history,
        )
        return ChatResponse(response=response_text)
    except ClaudeAPIError:
        raise
    except Exception as e:
        logger.exception(f"Chat error: {e}")
        raise HTTPException(status_code=500, detail="Failed to process chat request")


async def stream_response(
    db: AsyncSession,
    user_id: str,
    message: str,
    conversation_history,
) -> AsyncGenerator[str, None]:
    """Generate Server-Sent Events for streaming chat response."""
    try:
        chat_service = DobbyChatService()
        async for chunk in chat_service.chat_stream(
            db=db,
            user_id=user_id,
            message=message,
            conversation_history=conversation_history,
        ):
            # Format as SSE data event
            data = json.dumps({"type": "text", "content": chunk})
            yield f"data: {data}\n\n"

        # Send done event
        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    except ClaudeAPIError as e:
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

    Each event is a JSON object with:
    - type: "text" | "error" | "done"
    - content: The text chunk (for "text" type)
    - error: The error message (for "error" type)
    """
    return StreamingResponse(
        stream_response(
            db=db,
            user_id=str(current_user.id),
            message=request.message,
            conversation_history=request.conversation_history,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
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
        chat_service = DobbyChatService()
        response_text = await chat_service.chat(
            db=db,
            user_id=str(user.id),
            message=request.message,
            conversation_history=request.conversation_history,
        )
        return ChatResponse(response=response_text)
    except ClaudeAPIError:
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

    return StreamingResponse(
        stream_response(
            db=db,
            user_id=str(user.id),
            message=request.message,
            conversation_history=request.conversation_history,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
