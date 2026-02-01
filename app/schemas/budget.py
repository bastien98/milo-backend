from datetime import datetime
from typing import Optional, List

from pydantic import BaseModel, Field


class CategoryAllocation(BaseModel):
    """Category allocation within a budget."""
    category: str
    amount: float = Field(..., gt=0)
    is_locked: bool = False


class BudgetBase(BaseModel):
    """Base budget schema with common fields."""
    monthly_amount: float = Field(..., gt=0)
    category_allocations: Optional[List[CategoryAllocation]] = None
    notifications_enabled: bool = True
    alert_thresholds: Optional[List[float]] = Field(default=[0.5, 0.75, 0.9])


class BudgetCreate(BudgetBase):
    """Schema for creating a new budget."""
    pass


class BudgetUpdate(BaseModel):
    """Schema for updating a budget. All fields are optional."""
    monthly_amount: Optional[float] = Field(None, gt=0)
    category_allocations: Optional[List[CategoryAllocation]] = None
    notifications_enabled: Optional[bool] = None
    alert_thresholds: Optional[List[float]] = None


class BudgetResponse(BudgetBase):
    """Schema for budget response."""
    id: str
    user_id: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class BudgetNotFoundResponse(BaseModel):
    """Response when no budget is found."""
    error: str = "No budget found"
    code: str = "NO_BUDGET"


class CategoryProgress(BaseModel):
    """Progress for a single category (Activity Rings data)."""
    category_id: str  # Enum name, e.g., "MEAT_FISH"
    name: str  # Display name, e.g., "Meat & Fish"
    limit_amount: float  # The budget allocation for this category
    spent_amount: float  # Actual spending in this category
    is_over_budget: bool  # True if spent_amount > limit_amount
    over_budget_amount: Optional[float] = None  # Amount over budget (only if over)
    is_locked: bool  # Whether this category allocation is locked


class BudgetProgressResponse(BaseModel):
    """Schema for budget progress response."""
    budget: BudgetResponse
    current_spend: float
    days_elapsed: int
    days_in_month: int
    category_progress: List[CategoryProgress]


class CategoryBreakdown(BaseModel):
    """Category breakdown in budget suggestion."""
    category: str
    average_spend: float
    suggested_budget: float
    percentage: float


class SavingsOption(BaseModel):
    """Savings option in budget suggestion."""
    label: str
    amount: float
    savings_percentage: int


class BudgetSuggestionResponse(BaseModel):
    """Schema for budget suggestion response."""
    suggested_amount: float
    based_on_months: int
    average_monthly_spend: float
    category_breakdown: List[CategoryBreakdown]
    savings_options: List[SavingsOption]
