from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_current_db_user
from app.models.user import User
from app.db.repositories.budget_repo import BudgetRepository
from app.services.budget_service import BudgetService
from app.schemas.budget import (
    BudgetCreate,
    BudgetUpdate,
    BudgetResponse,
    BudgetNotFoundResponse,
    BudgetProgressResponse,
    BudgetSuggestionResponse,
    CategoryAllocation,
)

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
        created_at=budget.created_at,
        updated_at=budget.updated_at,
    )


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
        clear_category_allocations=clear_category_allocations,
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
    current_user: User = Depends(get_current_db_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Delete the user's budget.

    Returns:
    - 204: Budget deleted successfully (no content)
    - 401: Invalid or missing authentication token
    - 404: No budget found
    """
    repo = BudgetRepository(db)
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
