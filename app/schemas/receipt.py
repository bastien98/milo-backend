from datetime import date, datetime, time
from typing import Optional, List

from pydantic import BaseModel

from app.models.enums import ReceiptStatus, ReceiptSource


class ExtractedItem(BaseModel):
    item_id: str  # UUID from the transactions table
    item_name: str  # Product description text from receipt (original casing)
    item_price: float
    quantity: int = 1
    unit_price: Optional[float] = None
    category: str
    normalized_name: Optional[str] = None  # Cleaned name for semantic search
    normalized_brand: Optional[str] = None  # Brand name only for semantic search
    is_premium: bool = False  # True if premium brand, False if store/house brand
    is_discount: bool = False  # True for discount/bonus lines
    is_deposit: bool = False  # True for any deposit line (charge or refund)
    is_deposit_refund: bool = False  # True only for deposit refund lines
    granular_category: Optional[str] = None  # Detailed category (~200 options)
    unit_of_measure: Optional[str] = None  # kg/g/l/ml/piece
    weight_or_volume: Optional[float] = None
    price_per_unit_measure: Optional[float] = None
    # Data Platform fields (dp_)
    dp_expanded_description: Optional[str] = None
    dp_pack_quantity: Optional[int] = None
    dp_pack_size: Optional[float] = None
    dp_pack_unit: Optional[str] = None

    dp_product_variant: Optional[str] = None
    dp_article_code: Optional[str] = None
    dp_is_bio: bool = False
    lookup_key: Optional[str] = None


class ReceiptUploadResponse(BaseModel):
    receipt_id: str
    status: ReceiptStatus
    store_name: Optional[str] = None
    receipt_date: Optional[date] = None
    receipt_time: Optional[time] = None
    total_amount: Optional[float] = None
    payment_method: Optional[str] = None
    store_branch: Optional[str] = None
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
    receipt_time: Optional[time] = None
    total_amount: Optional[float] = None
    payment_method: Optional[str] = None
    store_branch: Optional[str] = None
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


# Grouped receipts (transactions grouped by store + date)


class GroupedReceiptTransaction(BaseModel):
    """A single transaction within a grouped receipt."""

    item_id: str  # UUID from the transactions table
    item_name: str  # Product description text from receipt (original casing)
    item_price: float
    quantity: int
    unit_price: Optional[float]
    category: str
    normalized_name: Optional[str] = None  # Cleaned name for semantic search
    normalized_brand: Optional[str] = None  # Brand name only for semantic search
    is_premium: bool = False  # True if premium brand, False if store/house brand
    is_discount: bool = False  # True for discount/bonus lines
    is_deposit: bool = False  # True for any deposit line (charge or refund)
    is_deposit_refund: bool = False  # True only for deposit refund lines
    granular_category: Optional[str] = None  # Detailed category (~200 options)
    unit_of_measure: Optional[str] = None
    weight_or_volume: Optional[float] = None
    price_per_unit_measure: Optional[float] = None
    # Data Platform fields (dp_)
    dp_expanded_description: Optional[str] = None
    dp_pack_quantity: Optional[int] = None
    dp_pack_size: Optional[float] = None
    dp_pack_unit: Optional[str] = None

    dp_product_variant: Optional[str] = None
    dp_article_code: Optional[str] = None
    dp_is_bio: bool = False
    lookup_key: Optional[str] = None


class GroupedReceipt(BaseModel):
    """Transactions grouped by receipt.

    The receipt_id is the actual database UUID, which can be used
    directly with DELETE /api/v2/receipts/{receipt_id}.
    """

    receipt_id: str  # UUID from the receipts table
    store_name: str
    receipt_date: date
    receipt_time: Optional[time] = None
    total_amount: float
    payment_method: Optional[str] = None
    store_branch: Optional[str] = None
    items_count: int
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
    receipt_deleted: bool = False  # True if the entire receipt was deleted (last item)


class ReceiptUploadAcceptedResponse(BaseModel):
    """Returned immediately from POST /upload (HTTP 202).

    The receipt has been created and background processing has started.
    Poll GET /receipts/{receipt_id}/status for progress.
    """

    receipt_id: str
    status: ReceiptStatus
    filename: str


class ReceiptStatusResponse(BaseModel):
    """Returned from GET /receipts/{receipt_id}/status.

    Includes filename for persistent UI state and detected_date
    once processing completes so the frontend knows which period to refresh.
    """

    receipt_id: str
    status: ReceiptStatus
    filename: Optional[str] = None
    detected_date: Optional[date] = None  # receipt_date once extracted
    store_name: Optional[str] = None
    total_amount: Optional[float] = None
    items_count: int = 0
    error_message: Optional[str] = None
    error_code: Optional[str] = None
