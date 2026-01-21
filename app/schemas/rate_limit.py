from datetime import datetime

from pydantic import BaseModel, Field


class RateLimitStatusResponse(BaseModel):
    """Response for rate limit status endpoint."""

    messages_used: int = Field(..., description="Number of messages used in current period")
    messages_limit: int = Field(..., description="Maximum messages allowed per period")
    messages_remaining: int = Field(..., description="Messages remaining in current period")
    receipts_used: int = Field(..., description="Number of receipt uploads used in current period")
    receipts_limit: int = Field(..., description="Maximum receipt uploads allowed per period")
    receipts_remaining: int = Field(..., description="Receipt uploads remaining in current period")
    period_start_date: datetime = Field(..., description="Start of current rate limit period (UTC)")
    period_end_date: datetime = Field(..., description="End of current rate limit period (UTC)")
    days_until_reset: int = Field(..., description="Days until the rate limit resets")


class RateLimitExceededResponse(BaseModel):
    """Response when rate limit is exceeded (429)."""

    error: str = Field(default="rate_limit_exceeded")
    message: str = Field(..., description="Human-readable error message")
    messages_used: int = Field(..., description="Number of messages used")
    messages_limit: int = Field(..., description="Maximum messages allowed")
    period_end_date: datetime = Field(..., description="When the rate limit resets (UTC)")
    retry_after_seconds: int = Field(..., description="Seconds until rate limit resets")
