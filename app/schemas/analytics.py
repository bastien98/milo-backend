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


class CategorySpending(BaseModel):
    name: str
    spent: float
    percentage: float
    transaction_count: int


class CategoryBreakdown(BaseModel):
    period: str
    start_date: date
    end_date: date
    total_spend: float
    categories: List[CategorySpending]


class StoreBreakdown(BaseModel):
    store_name: str
    period: str
    start_date: date
    end_date: date
    total_store_spend: float
    store_visits: int
    categories: List[CategorySpending]


class SpendingTrend(BaseModel):
    period: str
    start_date: date
    end_date: date
    total_spend: float
    transaction_count: int


class TrendsResponse(BaseModel):
    trends: List[SpendingTrend]
    period_type: str  # "week", "month", "year"
