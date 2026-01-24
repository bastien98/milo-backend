from datetime import date, datetime
from typing import Optional, List

from pydantic import BaseModel

from app.models.enums import ReceiptStatus, Category


class ExtractedItem(BaseModel):
    item_name: str
    item_price: float
    quantity: int = 1
    unit_price: Optional[float] = None
    category: Category
    health_score: Optional[int] = None  # 0-5, None for non-food items


class ReceiptUploadResponse(BaseModel):
    receipt_id: str
    status: ReceiptStatus
    store_name: Optional[str] = None
    receipt_date: Optional[date] = None
    total_amount: Optional[float] = None
    items_count: int = 0
    transactions: List[ExtractedItem] = []
    warnings: List[str] = []
    is_duplicate: bool = False
    duplicate_score: Optional[float] = None  # Reserved for future use (Veryfi doesn't provide score)


class ReceiptResponse(BaseModel):
    id: str
    user_id: str
    original_filename: str
    file_type: str
    status: ReceiptStatus
    store_name: Optional[str] = None
    receipt_date: Optional[date] = None
    total_amount: Optional[float] = None
    error_message: Optional[str] = None
    created_at: datetime
    processed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ReceiptListResponse(BaseModel):
    receipts: List[ReceiptResponse]
    total: int
    page: int
    page_size: int


class ReceiptRateLimitInfo(BaseModel):
    receipts_used: int
    receipts_limit: int
    period_end_date: datetime


class ReceiptDeleteResponse(BaseModel):
    success: bool
    message: str
    deleted_receipt_id: str
    rate_limit: ReceiptRateLimitInfo
