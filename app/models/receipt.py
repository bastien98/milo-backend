import uuid
from datetime import datetime, date, time
from typing import TYPE_CHECKING, Optional, List

from sqlalchemy import String, DateTime, Integer, Float, ForeignKey, Text, Enum, Date, Time, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import ReceiptStatus, ReceiptSource

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.transaction import Transaction


class Receipt(Base):
    __tablename__ = "receipts"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id"), nullable=False, index=True
    )

    # File metadata (nullable for bank imports which have no file)
    original_filename: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    file_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # pdf, jpg, png
    file_size_bytes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Processing status
    status: Mapped[ReceiptStatus] = mapped_column(
        Enum(ReceiptStatus), default=ReceiptStatus.PENDING
    )
    source: Mapped[ReceiptSource] = mapped_column(
        Enum(ReceiptSource, values_callable=lambda e: [m.value for m in e]),
        default=ReceiptSource.RECEIPT_UPLOAD,
        nullable=False
    )
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Extracted metadata
    store_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    receipt_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    total_amount: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # New insights fields
    receipt_time: Mapped[Optional[time]] = mapped_column(Time, nullable=True)
    payment_method: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    total_savings: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    store_branch: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    processed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="receipts")
    transactions: Mapped[List["Transaction"]] = relationship(
        "Transaction", back_populates="receipt", cascade="all, delete-orphan"
    )
