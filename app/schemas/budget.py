from datetime import datetime
from typing import Optional, List

from pydantic import BaseModel, Field, model_validator


class CategoryAllocation(BaseModel):
    """A category target (guardrail) within a budget."""
    category: str
    amount: float = Field(..., gt=0)


def _filter_zero_allocations(data):
    """Remove category allocations with zero/negative amounts (e.g. from rounding)."""
    if isinstance(data, dict):
        allocs = data.get('category_allocations')
        if allocs is not None:
            filtered = [a for a in allocs if isinstance(a, dict) and a.get('amount', 0) > 0]
            data['category_allocations'] = filtered
    return data


class BudgetBase(BaseModel):
    """Base budget schema with common fields."""
    monthly_amount: float = Field(..., gt=0)
    category_allocations: Optional[List[CategoryAllocation]] = None
    is_smart_budget: bool = True  # When true, budget auto-rolls to next month


class BudgetCreate(BudgetBase):
    """Schema for creating a new budget."""

    @model_validator(mode='before')
    @classmethod
    def filter_zero_allocations(cls, data):
        return _filter_zero_allocations(data)


class BudgetUpdate(BaseModel):
    """Schema for updating a budget. All fields are optional."""
    monthly_amount: Optional[float] = Field(None, gt=0)
    category_allocations: Optional[List[CategoryAllocation]] = None
    is_smart_budget: Optional[bool] = None  # Allows toggling smart budget

    @model_validator(mode='before')
    @classmethod
    def filter_zero_allocations(cls, data):
        return _filter_zero_allocations(data)


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
    """Progress for a single watched category (guardrail)."""
    category_id: str  # Enum name, e.g., "MEAT_FISH"
    name: str  # Display name, e.g., "Meat & Fish"
    limit_amount: float  # The category target
    spent_amount: float  # Actual spending in this category
    is_over_budget: bool  # True if spent_amount > limit_amount
    over_budget_amount: Optional[float] = None  # Amount over budget (only if over)


class BudgetProgressResponse(BaseModel):
    """Schema for budget progress response."""
    budget: BudgetResponse
    current_spend: float
    days_elapsed: int
    days_in_month: int
    category_progress: List[CategoryProgress]


# =============================================================================
# Budget History Schemas
# =============================================================================


class BudgetHistoryEntry(BaseModel):
    """Schema for a single budget history entry."""
    id: str
    user_id: str
    monthly_amount: float
    category_allocations: Optional[List[CategoryAllocation]] = None
    month: str  # Format: "YYYY-MM"
    was_smart_budget: bool
    was_deleted: bool
    created_at: datetime

    class Config:
        from_attributes = True


class BudgetHistoryResponse(BaseModel):
    """Schema for budget history response."""
    budget_history: List[BudgetHistoryEntry]
