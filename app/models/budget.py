import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional, List, Any

from sqlalchemy import String, DateTime, Float, ForeignKey, Boolean, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User


class Budget(Base):
    __tablename__ = "budgets"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True
    )

    # Budget configuration
    monthly_amount: Mapped[float] = mapped_column(Float, nullable=False)

    # Optional category allocations: [{category: string, amount: number, is_locked: boolean}]
    category_allocations: Mapped[Optional[List[Any]]] = mapped_column(
        JSONB, nullable=True
    )

    # Notification settings
    notifications_enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    # Alert thresholds as percentages (e.g., [0.5, 0.75, 0.9])
    alert_thresholds: Mapped[Optional[List[float]]] = mapped_column(
        JSONB, default=[0.5, 0.75, 0.9]
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="budget")

    __table_args__ = (
        Index("ix_budgets_user_id", "user_id"),
    )
