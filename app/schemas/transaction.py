from datetime import date, datetime
from typing import Optional, List, Literal

from pydantic import BaseModel, Field



class TransactionBase(BaseModel):
    store_name: str
    item_name: str
    item_price: float
    quantity: int = 1
    unit_price: Optional[float] = None
    category: str
    date: date
    health_score: Optional[int] = None  # 0-5, None for non-food items


class TransactionCreate(TransactionBase):
    pass


class TransactionUpdate(BaseModel):
    store_name: Optional[str] = None
    item_name: Optional[str] = None
    item_price: Optional[float] = None
    quantity: Optional[int] = None
    unit_price: Optional[float] = None
    category: Optional[str] = None
    date: Optional[date] = None
    health_score: Optional[int] = None


class TransactionResponse(TransactionBase):
    id: str
    user_id: str
    receipt_id: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class TransactionListResponse(BaseModel):
    transactions: List[TransactionResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class TransactionFilters(BaseModel):
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    store_name: Optional[str] = None
    category: Optional[str] = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=100)


class TransactionBulkDeleteRequest(BaseModel):
    """Request body for bulk deleting transactions by store and date range."""

    store_name: str = Field(..., description="Store name to delete transactions for")
    period: Literal["week", "month", "year"] = Field(
        ..., description="Time period type"
    )
    start_date: date = Field(..., description="Start date of the period (inclusive)")
    end_date: date = Field(..., description="End date of the period (inclusive)")


class TransactionBulkDeleteResponse(BaseModel):
    """Response for bulk delete operation."""

    success: bool
    deleted_count: int
    message: str
