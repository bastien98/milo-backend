"""Budget insights schemas - deterministic, rule-based insights without AI."""

from datetime import datetime
from typing import List, Optional, Literal

from pydantic import BaseModel, Field


# =============================================================================
# Belgian Benchmark Comparison
# =============================================================================


class BelgianBenchmarkComparison(BaseModel):
    """Comparison of user spending to Belgian household averages."""

    category: str
    user_percentage: float  # User's spending as % of total budget
    belgian_average_percentage: float  # Belgian average %
    difference_percentage: float  # How much more/less user spends (positive = more)
    comparison_text: str  # "You spend 20% more on Snacks than typical Belgian households"


class BelgianBenchmarksResponse(BaseModel):
    """Belgian benchmark comparisons for all categories."""

    comparisons: List[BelgianBenchmarkComparison]
    user_total_analyzed: float  # Total EUR analyzed for user
    data_source: str = "Belgian Household Budget Survey"


# =============================================================================
# Over-Budget Flags
# =============================================================================


class OverBudgetFlag(BaseModel):
    """Category that is consistently over budget."""

    category: str
    months_over: int  # How many of last N months over budget
    months_analyzed: int  # Total months analyzed (2-3)
    average_overage_percentage: float  # Average % over budget
    average_overage_amount: float  # Average EUR over budget
    severity: Literal["warning", "critical"]  # warning: 2/3, critical: 3/3


class OverBudgetFlagsResponse(BaseModel):
    """Categories consistently over budget."""

    flags: List[OverBudgetFlag]
    months_analyzed: int


# =============================================================================
# Quick Wins Calculator
# =============================================================================


class QuickWin(BaseModel):
    """Potential savings from cutting a category."""

    category: str
    current_monthly_spend: float
    suggested_cut_percentage: int = 10  # Default 10%
    monthly_savings: float
    yearly_savings: float
    message: str  # "Save 10 EUR/month on Alcohol = 120 EUR/year"


class QuickWinsResponse(BaseModel):
    """Quick wins - categories with savings potential."""

    quick_wins: List[QuickWin]
    total_potential_monthly_savings: float
    total_potential_yearly_savings: float


# =============================================================================
# Volatility Alerts
# =============================================================================


class VolatilityAlert(BaseModel):
    """Category with high spending variance."""

    category: str
    average_monthly_spend: float
    standard_deviation: float
    coefficient_of_variation: float  # CV = stddev / mean * 100
    min_month_spend: float
    max_month_spend: float
    volatility_level: Literal["moderate", "high", "very_high"]
    recommendation: str  # "Budget €X buffer for unpredictable spending"


class VolatilityAlertsResponse(BaseModel):
    """Categories with high month-to-month variance."""

    alerts: List[VolatilityAlert]
    months_analyzed: int


# =============================================================================
# Rich Progress & Health Score
# =============================================================================


class HealthScoreBreakdown(BaseModel):
    """Formula-based health score breakdown."""

    pace_score: int = Field(..., ge=0, le=40)  # 0-40 points: spending pace vs expected
    category_balance_score: int = Field(
        ..., ge=0, le=30
    )  # 0-30 points: how many categories over
    consistency_score: int = Field(..., ge=0, le=30)  # 0-30 points: volatility penalty


class RichProgressResponse(BaseModel):
    """Enhanced budget progress with projections."""

    # Daily budget
    daily_budget_remaining: float  # EUR/day for remaining days
    days_remaining: int

    # Projection
    projected_end_of_month: float  # Projected total spend
    projected_status: Literal["under_budget", "on_track", "over_budget"]
    projected_difference: float  # Amount under/over (positive = under budget)

    # Health score (0-100)
    health_score: int = Field(..., ge=0, le=100)
    health_score_breakdown: HealthScoreBreakdown
    health_score_label: str  # "Excellent", "Good", "Fair", "Needs Attention"


# =============================================================================
# Combined Insights Response
# =============================================================================


class BudgetInsightsResponse(BaseModel):
    """Combined response with all budget insights."""

    belgian_benchmarks: Optional[BelgianBenchmarksResponse] = None
    over_budget_flags: Optional[OverBudgetFlagsResponse] = None
    quick_wins: Optional[QuickWinsResponse] = None
    volatility_alerts: Optional[VolatilityAlertsResponse] = None
    rich_progress: Optional[RichProgressResponse] = None

    # Metadata
    generated_at: datetime
    data_freshness: str  # "Based on spending through Feb 5, 2026"
