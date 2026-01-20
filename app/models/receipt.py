import uuid
from datetime import datetime, date
from typing import TYPE_CHECKING, Optional, List

from sqlalchemy import String, DateTime, Integer, Float, ForeignKey, Text, Enum, Date
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import ReceiptStatus

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

    # File metadata
    original_filename: Mapped[str] = mapped_column(String, nullable=False)
    file_type: Mapped[str] = mapped_column(String, nullable=False)  # pdf, jpg, png
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)

    # Processing status
    status: Mapped[ReceiptStatus] = mapped_column(
        Enum(ReceiptStatus), default=ReceiptStatus.PENDING
    )
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Extracted metadata
    store_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    receipt_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    total_amount: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()"
    )
    processed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="receipts")
    transactions: Mapped[List["Transaction"]] = relationship(
        "Transaction", back_populates="receipt", cascade="all, delete-orphan"
    )
