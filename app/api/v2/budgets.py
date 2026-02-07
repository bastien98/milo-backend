from datetime import datetime, date
from dateutil.relativedelta import relativedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_current_db_user
from app.models.user import User
from app.db.repositories.budget_repo import BudgetRepository
from app.db.repositories.budget_history_repo import BudgetHistoryRepository
from app.services.budget_service import BudgetService
from app.services.budget_insights_service import BudgetInsightsService
from app.schemas.budget import (
    BudgetCreate,
    BudgetUpdate,
    BudgetResponse,
    BudgetNotFoundResponse,
    BudgetProgressResponse,
    BudgetSuggestionResponse,
    CategoryAllocation,
    BudgetHistoryEntry,
    BudgetHistoryResponse,
)
from app.schemas.budget_ai import SimpleBudgetSuggestionResponse
from app.schemas.budget_insights import BudgetInsightsResponse

router = APIRouter()


@router.get(
    "",
    response_model=BudgetResponse,
    responses={
        404: {
            "model": BudgetNotFoundResponse,
            "description": "No budget found",
        }
    },
)
async def get_budget(
    current_user: User = Depends(get_current_db_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get the user's current budget.

    Returns:
    - 200: Budget found
    - 404: No budget set for this user
    - 401: Invalid or missing authentication token
    """
    repo = BudgetRepository(db)
    budget = await repo.get_by_user_id(current_user.id)

    if not budget:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "No budget found",
                "code": "NO_BUDGET",
            },
        )

    return BudgetResponse(
        id=budget.id,
        user_id=budget.user_id,
        monthly_amount=budget.monthly_amount,
        category_allocations=[
            CategoryAllocation(**alloc)
            for alloc in (budget.category_allocations or [])
        ]
        if budget.category_allocations
        else None,
        notifications_enabled=budget.notifications_enabled,
        alert_thresholds=budget.alert_thresholds,
        is_smart_budget=budget.is_smart_budget,
        created_at=budget.created_at,
        updated_at=budget.updated_at,
    )


@router.get(
    "/history",
    response_model=BudgetHistoryResponse,
)
async def get_budget_history(
    current_user: User = Depends(get_current_db_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get the user's budget history.

    Returns all historical budget records for the authenticated user,
    ordered by month (newest first).

    Returns:
    - 200: Budget history list
    - 401: Invalid or missing authentication token
    """
    history_repo = BudgetHistoryRepository(db)
    history_entries = await history_repo.get_by_user_id(current_user.id)

    return BudgetHistoryResponse(
        budget_history=[
            BudgetHistoryEntry(
                id=entry.id,
                user_id=entry.user_id,
                monthly_amount=entry.monthly_amount,
                category_allocations=[
                    CategoryAllocation(**alloc)
                    for alloc in (entry.category_allocations or [])
                ]
                if entry.category_allocations
                else None,
                month=entry.month,
                was_smart_budget=entry.was_smart_budget,
                was_deleted=entry.was_deleted,
                created_at=entry.created_at,
            )
            for entry in history_entries
        ]
    )


@router.post(
    "/auto-rollover",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def auto_rollover_budget(
    current_user: User = Depends(get_current_db_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Check if current month needs a budget auto-created from previous month.

    This endpoint is idempotent - calling it multiple times will not create
    duplicate budgets. It checks if:
    1. A budget already exists for the current month (if so, does nothing)
    2. Previous month had a smart budget that wasn't deleted (if so, creates new budget)

    Returns:
    - 204: Success (budget created or nothing to do)
    - 401: Invalid or missing authentication token
    """
    budget_repo = BudgetRepository(db)
    history_repo = BudgetHistoryRepository(db)

    # Get current month in "YYYY-MM" format
    today = date.today()
    current_month = today.strftime("%Y-%m")

    # Check if budget already exists for current month
    existing_budget = await budget_repo.get_by_user_id(current_user.id)
    if existing_budget:
        # Budget already exists, check if it's for current month
        budget_month = existing_budget.created_at.strftime("%Y-%m")
        if budget_month == current_month:
            # Budget exists for current month, nothing to do
            return None

    # Get previous month
    previous_month_date = today - relativedelta(months=1)
    previous_month = previous_month_date.strftime("%Y-%m")

    # Get previous month's budget from history
    previous_budget = await history_repo.get_by_user_and_month(
        current_user.id, previous_month
    )

    # Check rollover conditions
    if not previous_budget:
        # No previous budget exists
        return None

    if not previous_budget.was_smart_budget:
        # Previous budget was not a smart budget
        return None

    if previous_budget.was_deleted:
        # Previous budget was deleted
        return None

    # Create new budget for current month (copying from previous month)
    new_budget = await budget_repo.upsert(
        user_id=current_user.id,
        monthly_amount=previous_budget.monthly_amount,
        category_allocations=previous_budget.category_allocations,
        notifications_enabled=previous_budget.notifications_enabled,
        alert_thresholds=previous_budget.alert_thresholds,
        is_smart_budget=True,  # Inherit smart budget status
    )

    # Create history entry for the new budget
    await history_repo.upsert(
        user_id=current_user.id,
        monthly_amount=new_budget.monthly_amount,
        month=current_month,
        was_smart_budget=new_budget.is_smart_budget,
        category_allocations=new_budget.category_allocations,
        was_deleted=False,
        notifications_enabled=new_budget.notifications_enabled,
        alert_thresholds=new_budget.alert_thresholds,
    )

    return None


@router.post(
    "",
    response_model=BudgetResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_budget(
    budget_data: BudgetCreate,
    current_user: User = Depends(get_current_db_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Create a new budget (or replace existing).

    If a budget already exists for the user, it will be replaced.

    Returns:
    - 201: Budget created successfully
    - 400: Invalid input data
    - 401: Invalid or missing authentication token
    """
    repo = BudgetRepository(db)
    history_repo = BudgetHistoryRepository(db)

    # Convert category allocations to dict format for storage
    category_allocations = None
    if budget_data.category_allocations:
        category_allocations = [
            {
                "category": alloc.category,
                "amount": alloc.amount,
                "is_locked": alloc.is_locked,
            }
            for alloc in budget_data.category_allocations
        ]

    # Upsert (create or replace)
    budget = await repo.upsert(
        user_id=current_user.id,
        monthly_amount=budget_data.monthly_amount,
        category_allocations=category_allocations,
        notifications_enabled=budget_data.notifications_enabled,
        alert_thresholds=budget_data.alert_thresholds,
        is_smart_budget=budget_data.is_smart_budget,
    )

    # Create/update budget history entry for current month
    current_month = date.today().strftime("%Y-%m")
    await history_repo.upsert(
        user_id=current_user.id,
        monthly_amount=budget.monthly_amount,
        month=current_month,
        was_smart_budget=budget.is_smart_budget,
        category_allocations=budget.category_allocations,
        was_deleted=False,
        notifications_enabled=budget.notifications_enabled,
        alert_thresholds=budget.alert_thresholds,
    )

    return BudgetResponse(
        id=budget.id,
        user_id=budget.user_id,
        monthly_amount=budget.monthly_amount,
        category_allocations=[
            CategoryAllocation(**alloc)
            for alloc in (budget.category_allocations or [])
        ]
        if budget.category_allocations
        else None,
        notifications_enabled=budget.notifications_enabled,
        alert_thresholds=budget.alert_thresholds,
        is_smart_budget=budget.is_smart_budget,
        created_at=budget.created_at,
        updated_at=budget.updated_at,
    )


@router.put(
    "",
    response_model=BudgetResponse,
    responses={
        404: {
            "model": BudgetNotFoundResponse,
            "description": "No budget found",
        }
    },
)
async def update_budget(
    budget_data: BudgetUpdate,
    current_user: User = Depends(get_current_db_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Update an existing budget.

    All fields are optional - only provided fields are updated.

    Returns:
    - 200: Budget updated successfully
    - 400: Invalid input data
    - 401: Invalid or missing authentication token
    - 404: No budget found (use POST to create first)
    """
    repo = BudgetRepository(db)
    history_repo = BudgetHistoryRepository(db)
    budget = await repo.get_by_user_id(current_user.id)

    if not budget:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "No budget found",
                "code": "NO_BUDGET",
            },
        )

    # Convert category allocations to dict format for storage
    category_allocations = None
    clear_category_allocations = False
    if budget_data.category_allocations is not None:
        if budget_data.category_allocations:
            category_allocations = [
                {
                    "category": alloc.category,
                    "amount": alloc.amount,
                    "is_locked": alloc.is_locked,
                }
                for alloc in budget_data.category_allocations
            ]
        else:
            # Empty list means clear the allocations
            clear_category_allocations = True

    budget = await repo.update(
        budget=budget,
        monthly_amount=budget_data.monthly_amount,
        category_allocations=category_allocations,
        notifications_enabled=budget_data.notifications_enabled,
        alert_thresholds=budget_data.alert_thresholds,
        is_smart_budget=budget_data.is_smart_budget,
        clear_category_allocations=clear_category_allocations,
    )

    # Update budget history entry for current month
    current_month = date.today().strftime("%Y-%m")
    await history_repo.upsert(
        user_id=current_user.id,
        monthly_amount=budget.monthly_amount,
        month=current_month,
        was_smart_budget=budget.is_smart_budget,
        category_allocations=budget.category_allocations,
        was_deleted=False,
        notifications_enabled=budget.notifications_enabled,
        alert_thresholds=budget.alert_thresholds,
    )

    return BudgetResponse(
        id=budget.id,
        user_id=budget.user_id,
        monthly_amount=budget.monthly_amount,
        category_allocations=[
            CategoryAllocation(**alloc)
            for alloc in (budget.category_allocations or [])
        ]
        if budget.category_allocations
        else None,
        notifications_enabled=budget.notifications_enabled,
        alert_thresholds=budget.alert_thresholds,
        is_smart_budget=budget.is_smart_budget,
        created_at=budget.created_at,
        updated_at=budget.updated_at,
    )


@router.delete(
    "",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        404: {
            "model": BudgetNotFoundResponse,
            "description": "No budget found",
        }
    },
)
async def delete_budget(
    month: str = Query(None, description="Month to delete in YYYY-MM format. Defaults to current month."),
    current_user: User = Depends(get_current_db_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Delete the user's budget.

    This marks the budget as deleted in history (prevents auto-rollover)
    and removes it from the active budgets table (only for current month).

    Parameters:
    - month: Optional month in YYYY-MM format. If provided, marks that month's
      history as deleted. If it's the current month, also deletes the active budget.

    Returns:
    - 204: Budget deleted successfully (no content)
    - 401: Invalid or missing authentication token
    - 404: No budget found
    """
    repo = BudgetRepository(db)
    history_repo = BudgetHistoryRepository(db)

    current_month = date.today().strftime("%Y-%m")
    target_month = month if month else current_month

    # Mark budget as deleted in history for the target month
    await history_repo.mark_as_deleted(current_user.id, target_month)

    if target_month == current_month:
        # Current month: also delete from active budgets table
        deleted = await repo.delete_by_user_id(current_user.id)

        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "error": "No budget found",
                    "code": "NO_BUDGET",
                },
            )

    return None


@router.get(
    "/progress",
    response_model=BudgetProgressResponse,
    responses={
        404: {
            "model": BudgetNotFoundResponse,
            "description": "No budget found",
        }
    },
)
async def get_budget_progress(
    current_user: User = Depends(get_current_db_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get current budget progress with spending data for the current month.

    Returns:
    - 200: Budget progress data
    - 401: Invalid or missing authentication token
    - 404: No budget found
    """
    repo = BudgetRepository(db)
    budget = await repo.get_by_user_id(current_user.id)

    if not budget:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "No budget found",
                "code": "NO_BUDGET",
            },
        )

    service = BudgetService(db)
    return await service.get_budget_progress(current_user.id, budget)


@router.get(
    "/suggestion",
    response_model=BudgetSuggestionResponse,
    responses={
        404: {
            "description": "No spending history found",
        }
    },
)
async def get_budget_suggestion(
    months: int = Query(
        default=3,
        ge=1,
        le=12,
        description="Number of months to analyze for the suggestion",
    ),
    current_user: User = Depends(get_current_db_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Generate a smart budget suggestion based on historical spending.

    Analyzes spending over the specified number of previous complete months
    and provides a suggested budget amount with category breakdown and savings options.

    Returns:
    - 200: Budget suggestion data
    - 401: Invalid or missing authentication token
    - 404: No spending history found for the specified period
    """
    service = BudgetService(db)
    suggestion = await service.get_budget_suggestion(current_user.id, months)

    if not suggestion:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "No spending history found",
                "code": "NO_HISTORY",
            },
        )

    return suggestion


# =============================================================================
# AI-Powered Budget Endpoints
# =============================================================================


@router.get(
    "/ai-suggestion",
    response_model=SimpleBudgetSuggestionResponse,
    responses={
        404: {"description": "No spending history found"},
    },
)
async def get_budget_suggestion_simple(
    months: int = Query(
        default=3,
        ge=1,
        le=12,
        description="Number of months to analyze",
    ),
    target_amount: float | None = Query(
        default=None,
        gt=0,
        description="Optional target budget amount. Category allocations will be "
        "scaled proportionally to fit this target.",
    ),
    current_user: User = Depends(get_current_db_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Generate a budget recommendation based on historical spending.

    Analyzes spending patterns to provide:
    - Recommended monthly budget (10% below average spending)
    - Category allocations based on historical percentages

    When target_amount is provided:
    - Category allocations are scaled proportionally to fit the target

    Confidence levels:
    - High: 3+ months of data
    - Medium: 1-2 months of data
    - Low: No data (default Belgian averages used)

    Returns:
    - 200: Budget suggestion
    - 401: Invalid or missing authentication token
    """
    service = BudgetService(db)
    result = await service.get_simple_budget_suggestion(
        current_user.id, months, target_amount=target_amount
    )
    return result


# =============================================================================
# Budget Insights (Deterministic, No AI)
# =============================================================================


@router.get(
    "/insights",
    response_model=BudgetInsightsResponse,
    responses={
        404: {
            "model": BudgetNotFoundResponse,
            "description": "No budget found (required for progress insights)",
        }
    },
)
async def get_budget_insights(
    include_benchmarks: bool = Query(
        default=True,
        description="Include Belgian household benchmark comparisons",
    ),
    include_flags: bool = Query(
        default=True,
        description="Include over-budget category flags",
    ),
    include_quick_wins: bool = Query(
        default=True,
        description="Include quick wins (savings opportunities)",
    ),
    include_volatility: bool = Query(
        default=True,
        description="Include volatility alerts for unpredictable categories",
    ),
    include_progress: bool = Query(
        default=True,
        description="Include rich progress metrics (requires active budget)",
    ),
    current_user: User = Depends(get_current_db_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get budget insights based on spending history.

    All calculations are deterministic and formula-based (no AI).

    Features:
    - **Belgian Benchmarks**: Compare your spending to Belgian household averages
    - **Over-budget Flags**: Identify categories consistently over budget
    - **Quick Wins**: Calculate yearly savings from small category cuts
    - **Volatility Alerts**: Flag categories with unpredictable spending
    - **Rich Progress**: Daily pace, projections, and health score (0-100)

    Note: Progress insights require an active budget. Other insights work
    without a budget (based on spending history only).

    Returns:
    - 200: Budget insights data
    - 401: Invalid or missing authentication token
    - 404: No budget found (only if include_progress=true)
    """
    budget_repo = BudgetRepository(db)
    budget = await budget_repo.get_by_user_id(current_user.id)

    # Budget is required only if progress is requested
    if include_progress and not budget:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "No budget found",
                "code": "NO_BUDGET",
            },
        )

    insights_service = BudgetInsightsService(db)
    return await insights_service.get_all_insights(
        user_id=current_user.id,
        budget=budget,
        include_benchmarks=include_benchmarks,
        include_flags=include_flags,
        include_quick_wins=include_quick_wins,
        include_volatility=include_volatility,
        include_progress=include_progress,
    )
