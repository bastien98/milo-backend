import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional, List

from sqlalchemy import String, DateTime, Float, ForeignKey, Index, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.bank_connection import BankConnection
    from app.models.bank_transaction import BankTransaction


class BankAccount(Base):
    __tablename__ = "bank_accounts"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    connection_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("bank_connections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # EnableBanking account identifiers
    account_uid: Mapped[str] = mapped_column(String, nullable=False)  # EnableBanking account ID
    resource_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # Bank-specific ID

    # Account details
    iban: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    account_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    holder_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="EUR")  # ISO 4217

    # Balance (updated on sync)
    balance: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    balance_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # e.g., "closingBooked"

    # Sync status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_synced_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    connection: Mapped["BankConnection"] = relationship(
        "BankConnection", back_populates="accounts"
    )
    bank_transactions: Mapped[List["BankTransaction"]] = relationship(
        "BankTransaction", back_populates="account", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index(
            "ix_bank_accounts_connection_uid",
            "connection_id",
            "account_uid",
            unique=True,
        ),
    )
