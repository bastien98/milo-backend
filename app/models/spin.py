import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import String, DateTime, Float, Integer, Boolean, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User


class SpinTransaction(Base):
    __tablename__ = "spin_transactions"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    segment_index: Mapped[int] = mapped_column(Integer, nullable=False)
    segment_label: Mapped[str] = mapped_column(String, nullable=False)
    segment_type: Mapped[str] = mapped_column(String, nullable=False)  # cash, mystery, try_again, double_next, jackpot
    cash_value: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    is_jackpot: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_doubled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="spin_transactions")


class SpinBudget(Base):
    """Tracks global spin budget usage across all users."""
    __tablename__ = "spin_budget"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    total_budget: Mapped[float] = mapped_column(Float, nullable=False, default=1500.0)
    total_spent: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    total_spins: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), onupdate=func.now()
    )
