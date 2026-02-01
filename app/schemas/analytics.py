from typing import List, Optional, Dict
from datetime import date

from pydantic import BaseModel


# Category color mapping for Pie Chart visualization
CATEGORY_COLORS: Dict[str, str] = {
    "Meat & Fish": "#FF6B6B",
    "Alcohol": "#9B59B6",
    "Drinks (Soft/Soda)": "#3498DB",
    "Drinks (Water)": "#5DADE2",
    "Household": "#95A5A6",
    "Snacks & Sweets": "#F39C12",
    "Fresh Produce": "#2ECC71",
    "Dairy & Eggs": "#F5B041",
    "Ready Meals": "#E74C3C",
    "Bakery": "#D4AC0D",
    "Pantry": "#8D6E63",
    "Personal Care": "#EC407A",
    "Frozen": "#00BCD4",
    "Baby & Kids": "#FF8A65",
    "Pet Supplies": "#A1887F",
    "Tobacco": "#607D8B",
    "Other": "#BDC3C7",
}


class PieChartCategory(BaseModel):
    """Category data for Pie Chart visualization."""
    category_id: str  # Enum name, e.g., "MEAT_FISH"
    name: str  # Display name, e.g., "Meat & Fish"
    total_spent: float
    color_hex: str
    percentage: float
    transaction_count: int
    average_health_score: Optional[float] = None


class PieChartStore(BaseModel):
    """Store data for Pie Chart visualization."""
    store_name: str
    total_spent: float
    percentage: float
    visit_count: int
    average_health_score: Optional[float] = None


class PieChartSummaryResponse(BaseModel):
    """Response for analytics summary endpoint (Pie Chart)."""
    month: int
    year: int
    total_spent: float
    categories: List[PieChartCategory]
    stores: List[PieChartStore]


class StoreSpending(BaseModel):
    store_name: str
    amount_spent: float
    store_visits: int
    percentage: float
    average_health_score: Optional[float] = None  # Average health score for this store (0-5)


class PeriodSummary(BaseModel):
    period: str
    start_date: date
    end_date: date
    total_spend: float
    transaction_count: int
    stores: List[StoreSpending]
    average_health_score: Optional[float] = None  # Average health score for all food items (0-5)


class CategorySpending(BaseModel):
    name: str
    spent: float
    percentage: float
    transaction_count: int
    average_health_score: Optional[float] = None  # Average health score for this category (0-5)


class CategoryBreakdown(BaseModel):
    period: str
    start_date: date
    end_date: date
    total_spend: float
    categories: List[CategorySpending]
    average_health_score: Optional[float] = None  # Overall average health score (0-5)


class StoreBreakdown(BaseModel):
    store_name: str
    period: str
    start_date: date
    end_date: date
    total_store_spend: float
    store_visits: int
    categories: List[CategorySpending]
    average_health_score: Optional[float] = None  # Average health score at this store (0-5)
    total_items: int = 0  # Sum of all item quantities for this store in the period
    average_item_price: Optional[float] = None  # total_store_spend / total_items


class SpendingTrend(BaseModel):
    period: str
    start_date: date
    end_date: date
    total_spend: float
    transaction_count: int
    average_health_score: Optional[float] = None  # Average health score for this period (0-5)


class TrendsResponse(BaseModel):
    trends: List[SpendingTrend]
    period_type: str  # "week", "month", "year"


class PeriodMetadata(BaseModel):
    """Lightweight metadata for a single period."""
    period: str
    period_start: date
    period_end: date
    total_spend: float
    receipt_count: int
    store_count: int
    transaction_count: int
    total_items: int
    average_health_score: Optional[float] = None


class PeriodsResponse(BaseModel):
    """Response containing all periods with basic metadata."""
    periods: List[PeriodMetadata]
    total_periods: int


# ============== Aggregate Analytics Schemas ==============

class AggregateTotals(BaseModel):
    """Total values across the aggregate period."""
    total_spend: float
    total_transactions: int
    total_receipts: int
    total_items: int


class AggregateAverages(BaseModel):
    """Average values across the aggregate period."""
    average_spend_per_period: float
    average_transaction_value: float
    average_item_price: float
    average_health_score: Optional[float] = None
    average_receipts_per_period: float
    average_transactions_per_period: float
    average_items_per_receipt: float


class PeriodExtreme(BaseModel):
    """Represents an extreme (max/min) spending period."""
    period: str
    period_start: date
    period_end: date
    total_spend: float


class HealthScoreExtreme(BaseModel):
    """Represents an extreme (highest/lowest) health score period."""
    period: str
    period_start: date
    period_end: date
    average_health_score: float


class AggregateExtremes(BaseModel):
    """Extreme values (max/min) across the aggregate period."""
    max_spending_period: Optional[PeriodExtreme] = None
    min_spending_period: Optional[PeriodExtreme] = None
    highest_health_score_period: Optional[HealthScoreExtreme] = None
    lowest_health_score_period: Optional[HealthScoreExtreme] = None


class HealthScoreDistribution(BaseModel):
    """Distribution of health scores across transactions."""
    score_1: int = 0  # Unhealthy
    score_2: int = 0
    score_3: int = 0  # Neutral
    score_4: int = 0
    score_5: int = 0  # Healthy
    unscored: int = 0


class AggregateResponse(BaseModel):
    """Response for aggregate analytics across multiple periods."""
    period_type: str
    num_periods: int
    start_date: date
    end_date: date

    totals: AggregateTotals
    averages: AggregateAverages
    extremes: AggregateExtremes

    top_categories: List[CategorySpending]
    top_stores: List[StoreSpending]
    health_score_distribution: HealthScoreDistribution


# ============== All-Time Analytics Schemas ==============

class StoreByVisits(BaseModel):
    """Store ranked by visit count."""
    store_name: str
    visit_count: int
    rank: int


class StoreBySpend(BaseModel):
    """Store ranked by total spend."""
    store_name: str
    total_spent: float
    rank: int


class TopCategory(BaseModel):
    """Category ranked by total spend for all-time statistics."""
    name: str
    total_spent: float
    percentage: float
    transaction_count: int
    average_health_score: Optional[float] = None
    rank: int


class AllTimeResponse(BaseModel):
    """Response for all-time user statistics."""
    total_receipts: int
    total_items: int
    total_spend: float
    total_transactions: int
    average_item_price: Optional[float] = None
    average_health_score: Optional[float] = None
    top_stores_by_visits: List[StoreByVisits]
    top_stores_by_spend: List[StoreBySpend]
    top_categories: List[TopCategory]
    first_receipt_date: Optional[date] = None
    last_receipt_date: Optional[date] = None


# ============== Year Summary Analytics Schemas ==============

class YearStoreSpending(BaseModel):
    """Store spending breakdown for year summary."""
    store_name: str
    amount_spent: float
    store_visits: int
    percentage: float
    average_health_score: Optional[float] = None


class YearMonthlyBreakdown(BaseModel):
    """Monthly spending breakdown for year summary."""
    month: str  # e.g., "January"
    month_number: int  # 1-12
    total_spend: float
    receipt_count: int
    average_health_score: Optional[float] = None


class YearCategorySpending(BaseModel):
    """Category spending for year summary."""
    name: str
    spent: float
    percentage: float
    transaction_count: int
    average_health_score: Optional[float] = None


class YearSummaryResponse(BaseModel):
    """Response for year summary analytics."""
    year: int
    start_date: date
    end_date: date
    total_spend: float
    transaction_count: int
    receipt_count: int
    total_items: int
    average_health_score: Optional[float] = None
    stores: List[YearStoreSpending]
    monthly_breakdown: Optional[List[YearMonthlyBreakdown]] = None
    top_categories: List[YearCategorySpending]
