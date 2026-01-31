from datetime import datetime, timedelta
from typing import Optional, Any

from sqlalchemy import select, delete, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.budget_ai_insight import BudgetAIInsight, AIInsightFeedback


class BudgetAIInsightRepository:
    """Repository for managing AI-generated budget insights."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, insight_id: str) -> Optional[BudgetAIInsight]:
        """Get an insight by its ID."""
        result = await self.db.execute(
            select(BudgetAIInsight).where(BudgetAIInsight.id == insight_id)
        )
        return result.scalar_one_or_none()

    async def get_valid_suggestion(self, user_id: str) -> Optional[BudgetAIInsight]:
        """Get cached suggestion if it's less than 24 hours old."""
        cutoff_time = datetime.utcnow() - timedelta(hours=24)

        result = await self.db.execute(
            select(BudgetAIInsight)
            .where(
                and_(
                    BudgetAIInsight.user_id == user_id,
                    BudgetAIInsight.insight_type == "suggestion",
                    BudgetAIInsight.created_at >= cutoff_time,
                )
            )
            .order_by(BudgetAIInsight.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_latest_checkin(self, user_id: str) -> Optional[BudgetAIInsight]:
        """Get the most recent checkin for rate limiting purposes."""
        result = await self.db.execute(
            select(BudgetAIInsight)
            .where(
                and_(
                    BudgetAIInsight.user_id == user_id,
                    BudgetAIInsight.insight_type == "checkin",
                )
            )
            .order_by(BudgetAIInsight.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_todays_checkin(self, user_id: str) -> Optional[BudgetAIInsight]:
        """Get today's checkin if it exists (for rate limiting)."""
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

        result = await self.db.execute(
            select(BudgetAIInsight)
            .where(
                and_(
                    BudgetAIInsight.user_id == user_id,
                    BudgetAIInsight.insight_type == "checkin",
                    BudgetAIInsight.created_at >= today_start,
                )
            )
            .order_by(BudgetAIInsight.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_monthly_report(
        self, user_id: str, month: str
    ) -> Optional[BudgetAIInsight]:
        """Get cached monthly report for a specific month."""
        result = await self.db.execute(
            select(BudgetAIInsight)
            .where(
                and_(
                    BudgetAIInsight.user_id == user_id,
                    BudgetAIInsight.insight_type == "monthly_report",
                    BudgetAIInsight.month == month,
                )
            )
            .order_by(BudgetAIInsight.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        user_id: str,
        insight_type: str,
        ai_response: Any,
        input_data: Optional[Any] = None,
        month: Optional[str] = None,
        model_used: Optional[str] = None,
        tokens_used: Optional[int] = None,
        receipt_id: Optional[str] = None,
    ) -> BudgetAIInsight:
        """Create a new AI insight record."""
        insight = BudgetAIInsight(
            user_id=user_id,
            insight_type=insight_type,
            month=month,
            input_data=input_data,
            ai_response=ai_response,
            model_used=model_used,
            tokens_used=tokens_used,
            receipt_id=receipt_id,
        )
        self.db.add(insight)
        await self.db.flush()
        await self.db.refresh(insight)
        return insight

    async def invalidate_suggestions(self, user_id: str) -> int:
        """Delete all cached suggestions for a user (called on new receipt upload).

        Returns the number of deleted insights.
        """
        result = await self.db.execute(
            delete(BudgetAIInsight).where(
                and_(
                    BudgetAIInsight.user_id == user_id,
                    BudgetAIInsight.insight_type == "suggestion",
                )
            )
        )
        await self.db.flush()
        return result.rowcount

    async def add_feedback(
        self,
        insight_id: str,
        user_id: str,
        feedback_type: str,
    ) -> AIInsightFeedback:
        """Add user feedback for an AI insight."""
        feedback = AIInsightFeedback(
            insight_id=insight_id,
            user_id=user_id,
            feedback_type=feedback_type,
        )
        self.db.add(feedback)
        await self.db.flush()
        await self.db.refresh(feedback)
        return feedback

    async def get_feedback_for_insight(
        self, insight_id: str
    ) -> list[AIInsightFeedback]:
        """Get all feedback for a specific insight."""
        result = await self.db.execute(
            select(AIInsightFeedback).where(
                AIInsightFeedback.insight_id == insight_id
            )
        )
        return list(result.scalars().all())

    async def delete_old_insights(
        self, user_id: str, insight_type: str, keep_count: int = 10
    ) -> int:
        """Delete old insights, keeping only the most recent ones.

        Useful for cleaning up old receipt analyses or check-ins.
        Returns the number of deleted insights.
        """
        # Get IDs to keep
        keep_result = await self.db.execute(
            select(BudgetAIInsight.id)
            .where(
                and_(
                    BudgetAIInsight.user_id == user_id,
                    BudgetAIInsight.insight_type == insight_type,
                )
            )
            .order_by(BudgetAIInsight.created_at.desc())
            .limit(keep_count)
        )
        keep_ids = [row[0] for row in keep_result.all()]

        if not keep_ids:
            return 0

        # Delete all others
        result = await self.db.execute(
            delete(BudgetAIInsight).where(
                and_(
                    BudgetAIInsight.user_id == user_id,
                    BudgetAIInsight.insight_type == insight_type,
                    BudgetAIInsight.id.notin_(keep_ids),
                )
            )
        )
        await self.db.flush()
        return result.rowcount
