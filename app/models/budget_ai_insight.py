import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional, Any

from sqlalchemy import String, DateTime, Integer, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.receipt import Receipt


class BudgetAIInsight(Base):
    """Stores AI-generated budget insights for caching and history."""

    __tablename__ = "budget_ai_insights"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    # Type of insight: 'suggestion', 'checkin', 'receipt_analysis', 'monthly_report'
    insight_type: Mapped[str] = mapped_column(String(50), nullable=False)

    # Month in format '2026-01' (nullable for non-monthly insights)
    month: Mapped[Optional[str]] = mapped_column(String(7), nullable=True)

    # The input data sent to the AI (for debugging and reproducibility)
    input_data: Mapped[Optional[Any]] = mapped_column(JSONB, nullable=True)

    # The AI response
    ai_response: Mapped[Optional[Any]] = mapped_column(JSONB, nullable=True)

    # Model tracking
    model_used: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    tokens_used: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # For receipt_analysis type, link to the specific receipt
    receipt_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("receipts.id", ondelete="SET NULL"), nullable=True
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="ai_insights")
    receipt: Mapped[Optional["Receipt"]] = relationship("Receipt")
    feedback: Mapped[list["AIInsightFeedback"]] = relationship(
        "AIInsightFeedback", back_populates="insight", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_budget_ai_insights_user_type", "user_id", "insight_type"),
        Index("ix_budget_ai_insights_user_month", "user_id", "month"),
        Index("ix_budget_ai_insights_created", "created_at"),
    )


class AIInsightFeedback(Base):
    """Tracks user feedback on AI insights."""

    __tablename__ = "ai_insight_feedback"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    insight_id: Mapped[str] = mapped_column(
        String, ForeignKey("budget_ai_insights.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    # Feedback type: 'helpful', 'not_helpful', 'dismissed'
    feedback_type: Mapped[str] = mapped_column(String(20), nullable=False)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    insight: Mapped["BudgetAIInsight"] = relationship(
        "BudgetAIInsight", back_populates="feedback"
    )
    user: Mapped["User"] = relationship("User")

    __table_args__ = (
        Index("ix_ai_insight_feedback_insight", "insight_id"),
        Index("ix_ai_insight_feedback_user", "user_id"),
    )
