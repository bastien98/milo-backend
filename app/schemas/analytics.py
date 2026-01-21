from typing import List, Optional
from datetime import date

from pydantic import BaseModel


class StoreSpending(BaseModel):
    store_name: str
    amount_spent: float
    store_visits: int
    percentage: float


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
