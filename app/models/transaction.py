import uuid
from datetime import datetime
from datetime import date as date_type
from typing import TYPE_CHECKING, Optional

from sqlalchemy import String, DateTime, Integer, Float, ForeignKey, Date, Index, Text, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.receipt import Receipt


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id"), nullable=False, index=True
    )
    receipt_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("receipts.id"), nullable=True, index=True
    )

    # Item details
    store_name: Mapped[str] = mapped_column(String, nullable=False, index=True)
    item_name: Mapped[str] = mapped_column(String, nullable=False)
    item_price: Mapped[float] = mapped_column(Float, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    unit_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Semantic search fields
    original_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    normalized_name: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, index=True
    )
    normalized_brand: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, index=True
    )
    is_premium: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_deposit: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    granular_category: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True, index=True
    )

    # Categorization - sub-category display name from categories.csv
    category: Mapped[str] = mapped_column(
        String, nullable=False, index=True
    )

    # Health score (0-5, where 0 is unhealthy and 5 is very healthy)
    health_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Date
    date: Mapped[date_type] = mapped_column(Date, nullable=False, index=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()"
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="transactions")
    receipt: Mapped[Optional["Receipt"]] = relationship(
        "Receipt", back_populates="transactions"
    )

    __table_args__ = (
        Index("ix_transactions_user_date", "user_id", "date"),
        Index("ix_transactions_user_store", "user_id", "store_name"),
        Index("ix_transactions_user_category", "user_id", "category"),
    )
