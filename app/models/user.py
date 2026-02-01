import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional, List

from sqlalchemy import String, DateTime, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.transaction import Transaction
    from app.models.receipt import Receipt
    from app.models.user_profile import UserProfile
    from app.models.budget import Budget
    from app.models.budget_ai_insight import BudgetAIInsight
    from app.models.budget_history import BudgetHistory
    from app.models.bank_connection import BankConnection


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    firebase_uid: Mapped[str] = mapped_column(
        String, unique=True, nullable=False, index=True
    )
    email: Mapped[Optional[str]] = mapped_column(String, unique=True, nullable=True)
    display_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), onupdate=func.now()
    )

    # Relationships
    transactions: Mapped[List["Transaction"]] = relationship(
        "Transaction", back_populates="user", cascade="all, delete-orphan"
    )
    receipts: Mapped[List["Receipt"]] = relationship(
        "Receipt", back_populates="user", cascade="all, delete-orphan"
    )
    profile: Mapped[Optional["UserProfile"]] = relationship(
        "UserProfile", back_populates="user", cascade="all, delete-orphan", uselist=False
    )
    budget: Mapped[Optional["Budget"]] = relationship(
        "Budget", back_populates="user", cascade="all, delete-orphan", uselist=False
    )
    ai_insights: Mapped[List["BudgetAIInsight"]] = relationship(
        "BudgetAIInsight", back_populates="user", cascade="all, delete-orphan"
    )
    budget_history: Mapped[List["BudgetHistory"]] = relationship(
        "BudgetHistory", back_populates="user", cascade="all, delete-orphan"
    )
    bank_connections: Mapped[List["BankConnection"]] = relationship(
        "BankConnection", back_populates="user", cascade="all, delete-orphan"
    )
