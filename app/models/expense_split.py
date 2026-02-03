import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional, List

from sqlalchemy import String, DateTime, Integer, ForeignKey, JSON, Index, Float, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.receipt import Receipt


class ExpenseSplit(Base):
    """Represents a split session for a receipt."""

    __tablename__ = "expense_splits"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id"), nullable=False, index=True
    )
    receipt_id: Mapped[str] = mapped_column(
        String, ForeignKey("receipts.id"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), onupdate=func.now()
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="expense_splits")
    receipt: Mapped["Receipt"] = relationship("Receipt", back_populates="expense_split")
    participants: Mapped[List["SplitParticipant"]] = relationship(
        "SplitParticipant", back_populates="expense_split", cascade="all, delete-orphan"
    )
    assignments: Mapped[List["SplitAssignment"]] = relationship(
        "SplitAssignment", back_populates="expense_split", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_expense_splits_user_receipt", "user_id", "receipt_id", unique=True),
    )


class SplitParticipant(Base):
    """A participant in an expense split (friend)."""

    __tablename__ = "split_participants"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    split_id: Mapped[str] = mapped_column(
        String, ForeignKey("expense_splits.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    color: Mapped[str] = mapped_column(String(7), nullable=False)  # Hex color like #FF6B6B
    display_order: Mapped[int] = mapped_column(Integer, default=0)
    custom_amount: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # Custom split amount (null = equal split)
    is_me: Mapped[bool] = mapped_column(Boolean, default=False)  # True if this participant represents the current user
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    expense_split: Mapped["ExpenseSplit"] = relationship(
        "ExpenseSplit", back_populates="participants"
    )

    __table_args__ = (
        Index("ix_split_participants_split_order", "split_id", "display_order"),
    )


class SplitAssignment(Base):
    """Assignment of a transaction item to participants."""

    __tablename__ = "split_assignments"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    split_id: Mapped[str] = mapped_column(
        String, ForeignKey("expense_splits.id", ondelete="CASCADE"), nullable=False, index=True
    )
    transaction_id: Mapped[str] = mapped_column(
        String, ForeignKey("transactions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # JSON array of participant IDs who share this item
    participant_ids: Mapped[List[str]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), onupdate=func.now()
    )

    # Relationships
    expense_split: Mapped["ExpenseSplit"] = relationship(
        "ExpenseSplit", back_populates="assignments"
    )

    __table_args__ = (
        Index("ix_split_assignments_split_transaction", "split_id", "transaction_id", unique=True),
    )


class RecentFriend(Base):
    """Tracks recently used friends for quick-add functionality."""

    __tablename__ = "recent_friends"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    color: Mapped[str] = mapped_column(String(7), nullable=False)
    last_used_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    use_count: Mapped[int] = mapped_column(Integer, default=1)

    __table_args__ = (
        Index("ix_recent_friends_user_name", "user_id", "name", unique=True),
        Index("ix_recent_friends_user_last_used", "user_id", "last_used_at"),
    )
