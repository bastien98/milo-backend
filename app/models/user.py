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
    from app.models.user_enriched_profile import UserEnrichedProfile
    from app.models.budget import Budget
    from app.models.budget_history import BudgetHistory
    from app.models.cashback import CashbackTransaction, CashbackBalance
    from app.models.spin import SpinTransaction
    from app.models.referral import Referral
    from app.models.withdrawal import WithdrawalRequest
    from app.models.promo_interaction_event import PromoInteractionEvent


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
    budget_history: Mapped[List["BudgetHistory"]] = relationship(
        "BudgetHistory", back_populates="user", cascade="all, delete-orphan"
    )
    enriched_profile: Mapped[Optional["UserEnrichedProfile"]] = relationship(
        "UserEnrichedProfile", back_populates="user", cascade="all, delete-orphan", uselist=False
    )
    cashback_transactions: Mapped[List["CashbackTransaction"]] = relationship(
        "CashbackTransaction", back_populates="user", cascade="all, delete-orphan"
    )
    cashback_balance: Mapped[Optional["CashbackBalance"]] = relationship(
        "CashbackBalance", back_populates="user", cascade="all, delete-orphan", uselist=False
    )
    spin_transactions: Mapped[List["SpinTransaction"]] = relationship(
        "SpinTransaction", back_populates="user", cascade="all, delete-orphan"
    )
    referrals_made: Mapped[List["Referral"]] = relationship(
        "Referral", foreign_keys="[Referral.referrer_id]",
        back_populates="referrer", cascade="all, delete-orphan"
    )
    withdrawal_requests: Mapped[List["WithdrawalRequest"]] = relationship(
        "WithdrawalRequest", back_populates="user", cascade="all, delete-orphan"
    )
    promo_interaction_events: Mapped[List["PromoInteractionEvent"]] = relationship(
        "PromoInteractionEvent", back_populates="user", cascade="all, delete-orphan"
    )
