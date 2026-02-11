"""Schemas for the Promo Chat endpoint."""

from datetime import datetime, timezone
from typing import Optional, List

from pydantic import BaseModel, Field


class PromoChatMessage(BaseModel):
    """A single message in the promo chat conversation."""
    role: str = Field(..., description="Message role: 'user' or 'assistant'")
    content: str = Field(..., description="Message content")


class PromoChatRequest(BaseModel):
    """Request for the promo chat endpoint."""
    message: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="User's question about promotions (e.g., 'Any deals on coffee?' or 'What's on sale at Colruyt?')"
    )
    conversation_history: Optional[List[PromoChatMessage]] = Field(
        default=None,
        description="Previous conversation messages for context"
    )


class PromoResult(BaseModel):
    """A single promotion result."""
    product_name: str = Field(..., description="Product name")
    original_description: str = Field(..., description="Original description from retailer")
    brand: Optional[str] = Field(None, description="Product brand")
    category: str = Field(..., description="Product category")
    original_price: Optional[float] = Field(None, description="Original price in EUR")
    promo_price: Optional[float] = Field(None, description="Promotional price in EUR")
    savings: Optional[float] = Field(None, description="Savings amount in EUR")
    discount_percent: Optional[float] = Field(None, description="Discount percentage")
    promo_mechanism: Optional[str] = Field(None, description="Type of promotion (e.g., '1+1', '-30%')")
    unit_info: Optional[str] = Field(None, description="Size/unit information")
    retailer: str = Field(..., description="Store/retailer name")
    validity_start: Optional[str] = Field(None, description="Promotion start date")
    validity_end: Optional[str] = Field(None, description="Promotion end date")
    relevance_score: float = Field(..., description="How relevant this promo is to the query (0-1)")


class SearchQuery(BaseModel):
    """Structured search query extracted by the LLM."""
    search_text: str = Field(..., description="Main search text for vector search")
    product_keywords: List[str] = Field(default_factory=list, description="Product-related keywords")
    brands: List[str] = Field(default_factory=list, description="Specific brands mentioned")
    categories: List[str] = Field(default_factory=list, description="Product categories")
    granular_categories: List[str] = Field(default_factory=list, description="3 granular category guesses for filtering")
    retailers: List[str] = Field(default_factory=list, description="Specific retailers/stores")
    is_vague: bool = Field(False, description="Whether the query needs clarification")
    clarification_needed: Optional[str] = Field(None, description="What to ask the user for clarification")


class PromoChatResponse(BaseModel):
    """Response from the promo chat endpoint."""
    message: str = Field(..., description="AI response message")
    promos: List[PromoResult] = Field(default_factory=list, description="Matching promotions")
    search_query: Optional[SearchQuery] = Field(None, description="The structured query used for search")
    needs_clarification: bool = Field(False, description="Whether more user input is needed")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
