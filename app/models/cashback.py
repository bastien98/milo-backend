import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import String, DateTime, Float, Integer, Boolean, ForeignKey, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base
from app.models.enums import CashbackStatus, TierLevel, SpinType

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.receipt import Receipt


class CashbackTransaction(Base):
    __tablename__ = "cashback_transactions"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    receipt_id: Mapped[str] = mapped_column(
        String, ForeignKey("receipts.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    receipt_total: Mapped[float] = mapped_column(Float, nullable=False)

    # Legacy fields kept for backward compatibility (old transactions)
    cashback_amount: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    effective_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    spins_awarded: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    # New Milo Points fields
    points_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    fixed_points: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    grote_kar_points: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    kickstart_bonus_points: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    is_kickstart: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    is_streak_saver: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    spin_type: Mapped[Optional[SpinType]] = mapped_column(
        SAEnum(SpinType, name="spintype", values_callable=lambda e: [m.value for m in e]),
        nullable=True,
    )

    status: Mapped[CashbackStatus] = mapped_column(
        SAEnum(CashbackStatus, name="cashbackstatus",
               values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=CashbackStatus.CONFIRMED,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="cashback_transactions")
    receipt: Mapped["Receipt"] = relationship("Receipt")


class CashbackBalance(Base):
    __tablename__ = "cashback_balances"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True
    )

    # Legacy euro fields (kept for reference / backward compat)
    total_earned: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    total_paid_out: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    current_balance: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    spins_available: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    # New Milo Points fields
    points_balance: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    total_points_earned: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    total_points_paid_out: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    standard_spins: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    premium_spins: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    # Tier system (calendar month)
    tier_level: Mapped[TierLevel] = mapped_column(
        SAEnum(TierLevel, name="tierlevel", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=TierLevel.BRONZE,
        server_default="bronze",
    )
    tier_calculated_month: Mapped[Optional[str]] = mapped_column(String(7), nullable=True)  # "YYYY-MM"

    # Kickstart onboarding
    kickstart_tickets: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    kickstart_completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")

    # Grote Kar monthly cap tracking
    grote_kar_count_this_month: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    grote_kar_month: Mapped[Optional[str]] = mapped_column(String(7), nullable=True)  # "YYYY-MM"

    # Streak fields
    streak_week_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    streak_last_qualified_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    streak_level: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    streak_cycle_start_week: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)  # "YYYY-Www"

    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), onupdate=func.now()
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="cashback_balance")
