import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional, List, Any

from sqlalchemy import String, DateTime, Float, ForeignKey, Boolean, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User


class BudgetHistory(Base):
    """Historical budget records for tracking past budgets."""
    __tablename__ = "budget_history"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    # Budget configuration (copied from active budget)
    monthly_amount: Mapped[float] = mapped_column(Float, nullable=False)

    # Category allocations: [{category: string, amount: number, is_locked: boolean}]
    category_allocations: Mapped[Optional[List[Any]]] = mapped_column(
        JSONB, nullable=True
    )

    # Month in "YYYY-MM" format (e.g., "2026-01")
    month: Mapped[str] = mapped_column(String(7), nullable=False)

    # Smart budget status when this history entry was created
    was_smart_budget: Mapped[bool] = mapped_column(Boolean, nullable=False)

    # Whether the budget was deleted (prevents auto-rollover)
    was_deleted: Mapped[bool] = mapped_column(Boolean, default=False)

    # Notification settings (for rollover)
    notifications_enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    # Alert thresholds (for rollover)
    alert_thresholds: Mapped[Optional[List[float]]] = mapped_column(
        JSONB, default=[0.5, 0.75, 0.9]
    )

    # Timestamp
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="budget_history")

    __table_args__ = (
        UniqueConstraint("user_id", "month", name="uq_budget_history_user_month"),
        Index("idx_budget_history_user_month", "user_id", "month"),
    )
