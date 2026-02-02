from datetime import datetime
from typing import Optional, List, Literal

from pydantic import BaseModel, Field


# =============================================================================
# AI Budget Suggestion Schemas
# =============================================================================


class RecommendedBudget(BaseModel):
    """AI-recommended budget details."""

    amount: float = Field(..., description="Recommended monthly budget amount in EUR")
    confidence: Literal["high", "medium", "low"] = Field(
        ..., description="Confidence level of the recommendation"
    )
    reasoning: str = Field(..., description="Explanation for this recommendation")


class CategoryAllocationSuggestion(BaseModel):
    """AI-suggested category allocation."""

    category: str = Field(..., description="Category name")
    suggested_amount: float = Field(..., description="Suggested budget amount for this category")
    percentage: float = Field(..., description="Percentage of total budget")
    insight: str = Field(..., description="Reasoning for this allocation")
    savings_potential: Literal["high", "medium", "low", "none"] = Field(
        ..., description="Potential for savings in this category"
    )


class SavingsOpportunity(BaseModel):
    """Identified savings opportunity."""

    title: str = Field(..., description="Short title for the opportunity")
    description: str = Field(..., description="Actionable advice")
    potential_savings: float = Field(..., description="Estimated monthly savings in EUR")
    difficulty: Literal["easy", "medium", "hard"] = Field(
        ..., description="How difficult it is to implement"
    )


class SpendingInsight(BaseModel):
    """AI-identified spending insight."""

    type: Literal["pattern", "trend", "anomaly", "positive"] = Field(
        ..., description="Type of insight"
    )
    title: str = Field(..., description="Insight title")
    description: str = Field(..., description="What was noticed")
    recommendation: str = Field(..., description="What to do about it")


class AIBudgetSuggestionResponse(BaseModel):
    """Response for AI budget suggestion endpoint.

    Flat structure for iOS app compatibility.
    """

    # Core AI analysis fields
    recommended_budget: RecommendedBudget
    category_allocations: List[CategoryAllocationSuggestion]
    savings_opportunities: List[SavingsOpportunity]
    spending_insights: List[SpendingInsight]
    personalized_tips: List[str]
    budget_health_score: int = Field(..., ge=0, le=100, description="Overall budget health score")
    summary: str = Field(..., description="Personalized summary")

    # Metadata fields
    based_on_months: int = Field(..., description="Number of months analyzed")
    total_spend_analyzed: float = Field(..., description="Total spending analyzed in EUR")
    cached_at: Optional[datetime] = Field(None, description="When this was cached")

    # Target-based allocation fields (optional, only present when target_amount is provided)
    target_amount: Optional[float] = Field(
        None, description="The user-requested target budget amount (if specified)"
    )
    allocation_strategy: Optional[str] = Field(
        None, description="Explanation of how the budget was distributed to meet the target"
    )


# =============================================================================
# AI Check-in Schemas
# =============================================================================


class StatusSummary(BaseModel):
    """Current budget status summary."""

    emoji: str = Field(..., description="Status emoji")
    headline: str = Field(..., description="Short status headline")
    detail: str = Field(..., description="1-2 sentence explanation")


class ProjectedEndOfMonth(BaseModel):
    """Projected end-of-month spending."""

    amount: float = Field(..., description="Projected total spending")
    status: Literal["under_budget", "on_track", "over_budget"] = Field(
        ..., description="Budget status"
    )
    message: str = Field(..., description="What this means")


class FocusArea(BaseModel):
    """Category needing attention."""

    category: str = Field(..., description="Category name")
    status: Literal["good", "warning", "critical"] = Field(
        ..., description="Current status"
    )
    message: str = Field(..., description="Specific advice")


class AICheckInResponse(BaseModel):
    """Response for AI check-in endpoint."""

    greeting: str = Field(..., description="Personalized greeting")
    status_summary: StatusSummary
    daily_budget_remaining: float = Field(..., description="Budget per day for remaining days")
    projected_end_of_month: ProjectedEndOfMonth
    focus_areas: List[FocusArea]
    weekly_tip: str = Field(..., description="Actionable tip for next week")
    motivation: str = Field(..., description="Encouraging message")

    # Metadata
    days_remaining: int = Field(..., description="Days remaining in month")
    current_spend: float = Field(..., description="Current month spending")
    budget_amount: float = Field(..., description="Monthly budget amount")


# =============================================================================
# AI Receipt Analysis Schemas
# =============================================================================


class AIReceiptAnalysisRequest(BaseModel):
    """Request for AI receipt analysis."""

    receipt_id: str = Field(..., description="ID of the receipt to analyze")


class NotableItem(BaseModel):
    """Notable item from the receipt."""

    item: str = Field(..., description="Item name")
    observation: str = Field(..., description="Quick note about the item")


class AIReceiptAnalysisResponse(BaseModel):
    """Response for AI receipt analysis endpoint."""

    impact_summary: str = Field(..., description="One line about budget impact")
    emoji: str = Field(..., description="Appropriate emoji for status")
    status: Literal["great", "fine", "caution", "warning"] = Field(
        ..., description="Overall status"
    )
    notable_items: List[NotableItem]
    quick_tip: Optional[str] = Field(None, description="Optional relevant tip")

    # Context
    receipt_total: float = Field(..., description="Receipt total amount")
    budget_remaining_after: float = Field(..., description="Budget remaining after this receipt")
    percentage_used_after: float = Field(..., description="Percentage of budget used after")


# =============================================================================
# AI Monthly Report Schemas
# =============================================================================


class CategoryGrade(BaseModel):
    """Grade for a spending category."""

    category: str = Field(..., description="Category name")
    grade: Literal["A+", "A", "B", "C", "D", "F", "N/A"] = Field(
        ..., description="Letter grade (N/A if insufficient data)"
    )
    spent: float = Field(..., description="Amount spent")
    budget: Optional[float] = Field(None, description="Budget amount (if set)")
    comment: str = Field(..., description="Brief comment")


class TrendItem(BaseModel):
    """Spending trend."""

    type: Literal["improving", "declining", "stable"] = Field(
        ..., description="Trend direction"
    )
    area: str = Field(..., description="What's trending")
    detail: str = Field(..., description="Explanation")


class NextMonthFocus(BaseModel):
    """Recommendations for next month."""

    primary_goal: str = Field(..., description="Main thing to focus on")
    suggested_budget_adjustment: Optional[float] = Field(
        None, description="Suggested budget adjustment"
    )
    reason: str = Field(..., description="Why this adjustment")


class AIMonthlyReportResponse(BaseModel):
    """Response for AI monthly report endpoint."""

    headline: str = Field(..., description="Catchy summary of the month")
    grade: Literal["A+", "A", "B", "C", "D", "F"] = Field(
        ..., description="Overall grade"
    )
    score: int = Field(..., ge=0, le=100, description="Overall score")
    wins: List[str] = Field(..., description="Achievements from this month")
    challenges: List[str] = Field(..., description="Challenges faced")
    category_grades: List[CategoryGrade]
    trends: List[TrendItem]
    next_month_focus: NextMonthFocus
    fun_stats: List[str] = Field(..., description="Interesting stats")

    # Metadata
    month: str = Field(..., description="Month in YYYY-MM format")
    total_spent: float = Field(..., description="Total spending for the month")
    budget_amount: float = Field(..., description="Budget amount for the month")
    receipt_count: int = Field(..., description="Number of receipts")


# =============================================================================
# Feedback Schemas
# =============================================================================


class AIInsightFeedbackRequest(BaseModel):
    """Request for submitting feedback on an AI insight."""

    insight_id: str = Field(..., description="ID of the insight")
    feedback_type: Literal["helpful", "not_helpful", "dismissed"] = Field(
        ..., description="Type of feedback"
    )


class AIInsightFeedbackResponse(BaseModel):
    """Response for feedback submission."""

    id: str = Field(..., description="Feedback ID")
    insight_id: str = Field(..., description="Insight ID")
    feedback_type: str = Field(..., description="Feedback type")
    created_at: datetime = Field(..., description="When feedback was submitted")
