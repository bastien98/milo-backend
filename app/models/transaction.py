import uuid
from datetime import datetime
from datetime import date as date_type
from typing import TYPE_CHECKING, Optional

from sqlalchemy import String, DateTime, Integer, Float, ForeignKey, Date, Index, Text, Boolean, func
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
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    receipt_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("receipts.id", ondelete="CASCADE"), nullable=True, index=True
    )

    # Item details
    store_name: Mapped[str] = mapped_column(String, nullable=False, index=True)
    item_name: Mapped[str] = mapped_column(String, nullable=False)
    item_price: Mapped[float] = mapped_column(Float, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    unit_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Semantic search fields
    normalized_name: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, index=True
    )
    normalized_brand: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, index=True
    )
    is_premium: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_discount: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_deposit: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_deposit_refund: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    granular_category: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True, index=True
    )

    # Unit measure fields
    unit_of_measure: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    weight_or_volume: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    price_per_unit_measure: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Data Platform fields (dp_) — for EAN matching & Pinecone vector search
    dp_expanded_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    dp_pack_quantity: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    dp_pack_size: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    dp_pack_unit: Mapped[Optional[str]] = mapped_column(String(5), nullable=True)
    dp_product_variant: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    dp_article_code: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    dp_is_bio: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    dp_packaging_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    dp_product_name_no_brand: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # SKU lookup key (composite: normalized_name|pack_qty|pack_size|pack_unit|variant|is_bio)
    lookup_key: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)

    # Categorization - parent category name from app.core.categories
    category: Mapped[str] = mapped_column(
        String, nullable=False, index=True
    )

    # Date
    date: Mapped[date_type] = mapped_column(Date, nullable=False, index=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
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
