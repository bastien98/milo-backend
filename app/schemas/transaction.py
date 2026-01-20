from datetime import date, datetime
from typing import Optional, List

from pydantic import BaseModel, Field

from app.models.enums import Category


class TransactionBase(BaseModel):
    store_name: str
    item_name: str
    item_price: float
    quantity: int = 1
    unit_price: Optional[float] = None
    category: Category
    date: date


class TransactionCreate(TransactionBase):
    pass


class TransactionUpdate(BaseModel):
    store_name: Optional[str] = None
    item_name: Optional[str] = None
    item_price: Optional[float] = None
    quantity: Optional[int] = None
    unit_price: Optional[float] = None
    category: Optional[Category] = None
    date: Optional[date] = None


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
    category: Optional[Category] = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=100)
