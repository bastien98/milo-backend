from datetime import date, datetime
from typing import Optional, List

from pydantic import BaseModel

from app.models.enums import ReceiptStatus, ReceiptSource


class ExtractedItem(BaseModel):
    item_id: str  # UUID from the transactions table
    item_name: str  # Contains normalized_name for display
    item_price: float
    quantity: int = 1
    unit_price: Optional[float] = None
    category: str
    health_score: Optional[int] = None  # 0-5, None for non-food items
    # New fields for semantic search and granular categorization
    original_description: Optional[str] = None  # Raw OCR text
    normalized_name: Optional[str] = None  # Cleaned name for semantic search
    normalized_brand: Optional[str] = None  # Brand name only for semantic search
    is_premium: bool = False  # True if premium brand, False if store/house brand
    is_deposit: bool = False  # True for Leeggoed/Vidange items
    granular_category: Optional[str] = None  # Detailed category (~200 options)


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


# Grouped receipts (transactions grouped by store + date)


class GroupedReceiptTransaction(BaseModel):
    """A single transaction within a grouped receipt."""

    item_id: str  # UUID from the transactions table
    item_name: str  # Contains normalized_name for display
    item_price: float
    quantity: int
    unit_price: Optional[float]
    category: str
    health_score: Optional[int]
    # New fields for semantic search and granular categorization
    original_description: Optional[str] = None  # Raw OCR text
    normalized_name: Optional[str] = None  # Cleaned name for semantic search
    normalized_brand: Optional[str] = None  # Brand name only for semantic search
    is_premium: bool = False  # True if premium brand, False if store/house brand
    is_deposit: bool = False  # True for Leeggoed/Vidange items
    granular_category: Optional[str] = None  # Detailed category (~200 options)


class GroupedReceipt(BaseModel):
    """Transactions grouped by receipt.

    The receipt_id is the actual database UUID, which can be used
    directly with DELETE /api/v2/receipts/{receipt_id}.
    """

    receipt_id: str  # UUID from the receipts table
    store_name: str
    receipt_date: date
    total_amount: float
    items_count: int
    average_health_score: Optional[float]
    source: ReceiptSource  # receipt_upload or bank_import
    transactions: List[GroupedReceiptTransaction]


class GroupedReceiptListResponse(BaseModel):
    """Paginated response for grouped receipts."""

    receipts: List[GroupedReceipt]
    total: int
    page: int
    page_size: int
    total_pages: int


class LineItemDeleteResponse(BaseModel):
    """Response for deleting a line item from a receipt."""

    success: bool
    message: str
    updated_total_amount: float  # New receipt total after deletion
    updated_items_count: int  # New item count after deletion
    updated_average_health_score: Optional[float]  # New average health score
    receipt_deleted: bool = False  # True if the entire receipt was deleted (last item)
