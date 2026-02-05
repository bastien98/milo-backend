from datetime import datetime, timezone
from typing import Optional, List

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    """A single message in the chat conversation."""
    role: str = Field(..., description="Message role: 'user' or 'assistant'")
    content: str = Field(..., description="Message content")


class ChatRequest(BaseModel):
    """Request for the Dobby AI chat endpoint."""
    message: str = Field(..., min_length=1, max_length=2000, description="User's question about their transactional data")
    conversation_history: Optional[List[ChatMessage]] = Field(
        default=None,
        description="Previous conversation messages for context"
    )


class ChatResponse(BaseModel):
    """Response from the Dobby AI chat endpoint (non-streaming)."""
    response: str = Field(..., description="AI assistant's response")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ChatStreamChunk(BaseModel):
    """A single chunk of a streaming response."""
    type: str = Field(..., description="Chunk type: 'text', 'error', or 'done'")
    content: Optional[str] = Field(None, description="Text content for 'text' type")
    error: Optional[str] = Field(None, description="Error message for 'error' type")
