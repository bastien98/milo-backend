import uuid
from datetime import datetime
from datetime import date as date_type
from typing import TYPE_CHECKING, Optional
from enum import Enum

from sqlalchemy import String, DateTime, Float, ForeignKey, Index, Date, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import JSONB

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.bank_account import BankAccount
    from app.models.transaction import Transaction


class BankTransactionStatus(str, Enum):
    """Status of a bank transaction import."""

    PENDING = "pending"  # Fetched, awaiting user review
    IMPORTED = "imported"  # Imported to main transactions
    IGNORED = "ignored"  # User marked as ignore
    DUPLICATE = "duplicate"  # Detected as duplicate


class BankTransaction(Base):
    __tablename__ = "bank_transactions"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    account_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("bank_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # EnableBanking transaction identifiers
    transaction_id: Mapped[str] = mapped_column(String, nullable=False)  # EnableBanking ID
    entry_reference: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # Transaction details
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="EUR")

    # Counterparty info
    creditor_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    creditor_iban: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    debtor_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    debtor_iban: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # Transaction metadata
    booking_date: Mapped[date_type] = mapped_column(Date, nullable=False, index=True)
    value_date: Mapped[Optional[date_type]] = mapped_column(Date, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    remittance_info: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Import status
    status: Mapped[BankTransactionStatus] = mapped_column(
        String, default=BankTransactionStatus.PENDING, nullable=False
    )

    # Link to imported transaction (if imported)
    imported_transaction_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("transactions.id", ondelete="SET NULL"), nullable=True
    )

    # AI-suggested category (stored after first retrieval for consistency)
    suggested_category: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    category_confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Raw EnableBanking response (for debugging)
    raw_response: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    account: Mapped["BankAccount"] = relationship(
        "BankAccount", back_populates="bank_transactions"
    )
    imported_transaction: Mapped[Optional["Transaction"]] = relationship("Transaction")

    __table_args__ = (
        Index(
            "ix_bank_transactions_account_txn",
            "account_id",
            "transaction_id",
            unique=True,
        ),
        Index("ix_bank_transactions_status", "status"),
        Index("ix_bank_transactions_booking_date", "account_id", "booking_date"),
    )
