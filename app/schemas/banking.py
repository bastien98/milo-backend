from datetime import datetime, date
from typing import Optional, List
from enum import Enum

from pydantic import BaseModel, Field


# =============================================================================
# Enums
# =============================================================================


class BankConnectionStatusEnum(str, Enum):
    """Status of a bank connection."""

    PENDING = "pending"
    ACTIVE = "active"
    EXPIRED = "expired"
    REVOKED = "revoked"
    ERROR = "error"


class BankTransactionStatusEnum(str, Enum):
    """Status of a bank transaction import."""

    PENDING = "pending"
    IMPORTED = "imported"
    IGNORED = "ignored"
    DUPLICATE = "duplicate"


class CallbackTypeEnum(str, Enum):
    """Type of callback for OAuth redirect."""

    WEB = "web"
    MOBILE = "mobile"


# =============================================================================
# Bank Discovery
# =============================================================================


class BankInfo(BaseModel):
    """Information about an available bank."""

    name: str
    country: str
    bic: Optional[str] = None
    logo_url: Optional[str] = None
    max_consent_days: int = 90


class BankListResponse(BaseModel):
    """Response for list banks endpoint."""

    banks: List[BankInfo]
    country: str


# =============================================================================
# Bank Connections
# =============================================================================


class BankConnectionCreate(BaseModel):
    """Request to start bank connection."""

    bank_name: str = Field(..., description="Bank name from list")
    country: str = Field(
        ..., min_length=2, max_length=2, description="ISO 3166-1 alpha-2 country code"
    )
    callback_type: CallbackTypeEnum = Field(
        default=CallbackTypeEnum.WEB, description="Type of callback after authorization"
    )


class BankConnectionResponse(BaseModel):
    """Bank connection details."""

    id: str
    aspsp_name: str
    aspsp_country: str
    status: BankConnectionStatusEnum
    valid_until: Optional[datetime] = None
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    accounts_count: int = 0

    class Config:
        from_attributes = True


class BankConnectionAuthResponse(BaseModel):
    """Response when starting bank authorization."""

    connection_id: str
    redirect_url: str
    message: str = "Redirect user to this URL to complete bank authorization"


class BankConnectionListResponse(BaseModel):
    """Response for list connections endpoint."""

    connections: List[BankConnectionResponse]


# =============================================================================
# Bank Accounts
# =============================================================================


class BankAccountResponse(BaseModel):
    """Bank account details."""

    id: str
    connection_id: str
    account_uid: str
    iban: Optional[str] = None
    account_name: Optional[str] = None
    holder_name: Optional[str] = None
    currency: str = "EUR"
    balance: Optional[float] = None
    balance_type: Optional[str] = None
    is_active: bool = True
    last_synced_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


class BankAccountListResponse(BaseModel):
    """Response for list accounts endpoint."""

    accounts: List[BankAccountResponse]


class BankAccountSyncResponse(BaseModel):
    """Response for account sync endpoint.

    When requires_reauth is True, the bank connection has expired and
    the user needs to reconnect. The connection_id is provided so the
    iOS app can initiate the reconnection flow.
    """

    account_id: str
    balance: Optional[float] = None
    transactions_fetched: int = 0
    new_transactions: int = 0
    message: str
    requires_reauth: bool = False
    connection_id: Optional[str] = None


# =============================================================================
# Bank Transactions
# =============================================================================


class BankTransactionResponse(BaseModel):
    """Bank transaction details."""

    id: str
    account_id: str
    transaction_id: str
    amount: float
    currency: str
    creditor_name: Optional[str] = None
    debtor_name: Optional[str] = None
    booking_date: date
    value_date: Optional[date] = None
    description: Optional[str] = None
    status: BankTransactionStatusEnum
    imported_transaction_id: Optional[str] = None
    # AI-suggested category
    suggested_category: Optional[str] = None
    category_confidence: Optional[float] = None
    created_at: datetime

    class Config:
        from_attributes = True


class BankTransactionListResponse(BaseModel):
    """Response for list bank transactions endpoint."""

    transactions: List[BankTransactionResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


# =============================================================================
# Transaction Import
# =============================================================================


class TransactionImportItem(BaseModel):
    """Single transaction to import."""

    bank_transaction_id: str
    category: str = Field(..., description="Category for the imported transaction")
    store_name: Optional[str] = Field(None, description="Override store name")
    item_name: Optional[str] = Field(None, description="Override item/description")


class TransactionImportRequest(BaseModel):
    """Request to import bank transactions."""

    transactions: List[TransactionImportItem] = Field(
        ..., min_length=1, max_length=100, description="Transactions to import"
    )


class TransactionImportResult(BaseModel):
    """Result of importing a single transaction."""

    bank_transaction_id: str
    imported_transaction_id: Optional[str] = None
    success: bool
    error: Optional[str] = None


class TransactionImportResponse(BaseModel):
    """Response for transaction import endpoint."""

    imported_count: int
    failed_count: int
    results: List[TransactionImportResult]


class TransactionIgnoreRequest(BaseModel):
    """Request to ignore bank transactions."""

    transaction_ids: List[str] = Field(
        ..., min_length=1, max_length=100, description="Transaction IDs to ignore"
    )


class TransactionIgnoreResponse(BaseModel):
    """Response for ignore transactions endpoint."""

    ignored_count: int


class PendingTransactionsCountResponse(BaseModel):
    """Response for pending transactions count endpoint."""

    count: int = Field(..., description="Number of pending bank transactions awaiting import")
