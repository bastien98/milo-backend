import logging
from datetime import date
from dateutil.relativedelta import relativedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

from app.api.deps import get_db, get_current_db_user
from app.models.user import User
from app.db.repositories.budget_repo import BudgetRepository
from app.db.repositories.budget_history_repo import BudgetHistoryRepository
from app.services.budget_service import BudgetService
from app.schemas.budget import (
    BudgetCreate,
    BudgetUpdate,
    BudgetResponse,
    BudgetNotFoundResponse,
    BudgetProgressResponse,
    CategoryAllocation,
    BudgetHistoryEntry,
    BudgetHistoryResponse,
)

router = APIRouter()


def _budget_to_response(budget) -> BudgetResponse:
    """Convert a Budget model to a BudgetResponse schema."""
    return BudgetResponse(
        id=budget.id,
        user_id=budget.user_id,
        monthly_amount=budget.monthly_amount,
        category_allocations=[
            CategoryAllocation(category=alloc.get("category", ""), amount=alloc.get("amount", 0))
            for alloc in (budget.category_allocations or [])
        ]
        if budget.category_allocations
        else None,
        is_smart_budget=budget.is_smart_budget,
        created_at=budget.created_at,
        updated_at=budget.updated_at,
    )


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
    """Get the user's current budget."""
    repo = BudgetRepository(db)
    budget = await repo.get_by_user_id(current_user.id)

    if not budget:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "No budget found", "code": "NO_BUDGET"},
        )

    return _budget_to_response(budget)


@router.get(
    "/history",
    response_model=BudgetHistoryResponse,
)
async def get_budget_history(
    current_user: User = Depends(get_current_db_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the user's budget history, ordered by month (newest first)."""
    history_repo = BudgetHistoryRepository(db)
    history_entries = await history_repo.get_by_user_id(current_user.id)

    return BudgetHistoryResponse(
        budget_history=[
            BudgetHistoryEntry(
                id=entry.id,
                user_id=entry.user_id,
                monthly_amount=entry.monthly_amount,
                category_allocations=[
                    CategoryAllocation(category=alloc.get("category", ""), amount=alloc.get("amount", 0))
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
    Idempotent — safe to call multiple times.
    """
    budget_repo = BudgetRepository(db)
    history_repo = BudgetHistoryRepository(db)

    today = date.today()
    current_month = today.strftime("%Y-%m")

    # Check if budget already exists for current month
    existing_budget = await budget_repo.get_by_user_id(current_user.id)
    if existing_budget:
        budget_month = existing_budget.created_at.strftime("%Y-%m")
        if budget_month == current_month:
            return None

    # Get previous month's budget from history
    previous_month_date = today - relativedelta(months=1)
    previous_month = previous_month_date.strftime("%Y-%m")
    previous_budget = await history_repo.get_by_user_and_month(
        current_user.id, previous_month
    )

    if not previous_budget or not previous_budget.was_smart_budget or previous_budget.was_deleted:
        return None

    # Create new budget copying from previous month
    new_budget = await budget_repo.upsert(
        user_id=current_user.id,
        monthly_amount=previous_budget.monthly_amount,
        category_allocations=previous_budget.category_allocations,
        is_smart_budget=True,
    )

    await history_repo.upsert(
        user_id=current_user.id,
        monthly_amount=new_budget.monthly_amount,
        month=current_month,
        was_smart_budget=new_budget.is_smart_budget,
        category_allocations=new_budget.category_allocations,
        was_deleted=False,
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
    """Create a new budget (or replace existing)."""
    try:
        repo = BudgetRepository(db)
        history_repo = BudgetHistoryRepository(db)

        category_allocations = None
        if budget_data.category_allocations:
            category_allocations = [
                {"category": alloc.category, "amount": alloc.amount}
                for alloc in budget_data.category_allocations
            ]

        logger.info(f"Creating budget for user {current_user.id}: amount={budget_data.monthly_amount}")

        budget = await repo.upsert(
            user_id=current_user.id,
            monthly_amount=budget_data.monthly_amount,
            category_allocations=category_allocations,
            is_smart_budget=budget_data.is_smart_budget,
        )

        logger.info(f"Budget created: {budget.id}, saving history...")

        current_month = date.today().strftime("%Y-%m")
        await history_repo.upsert(
            user_id=current_user.id,
            monthly_amount=budget.monthly_amount,
            month=current_month,
            was_smart_budget=budget.is_smart_budget,
            category_allocations=budget.category_allocations,
            was_deleted=False,
        )

        logger.info(f"Budget history saved for {current_month}")

        return _budget_to_response(budget)
    except Exception as e:
        logger.error(f"Budget creation failed: {type(e).__name__}: {e}", exc_info=True)
        raise


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
    """Update an existing budget. All fields are optional."""
    repo = BudgetRepository(db)
    history_repo = BudgetHistoryRepository(db)
    budget = await repo.get_by_user_id(current_user.id)

    if not budget:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "No budget found", "code": "NO_BUDGET"},
        )

    category_allocations = None
    clear_category_allocations = False
    if budget_data.category_allocations is not None:
        if budget_data.category_allocations:
            category_allocations = [
                {"category": alloc.category, "amount": alloc.amount}
                for alloc in budget_data.category_allocations
            ]
        else:
            clear_category_allocations = True

    budget = await repo.update(
        budget=budget,
        monthly_amount=budget_data.monthly_amount,
        category_allocations=category_allocations,
        is_smart_budget=budget_data.is_smart_budget,
        clear_category_allocations=clear_category_allocations,
    )

    current_month = date.today().strftime("%Y-%m")
    await history_repo.upsert(
        user_id=current_user.id,
        monthly_amount=budget.monthly_amount,
        month=current_month,
        was_smart_budget=budget.is_smart_budget,
        category_allocations=budget.category_allocations,
        was_deleted=False,
    )

    return _budget_to_response(budget)


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
    """Delete the user's budget. Marks as deleted in history (prevents auto-rollover)."""
    repo = BudgetRepository(db)
    history_repo = BudgetHistoryRepository(db)

    current_month = date.today().strftime("%Y-%m")
    target_month = month if month else current_month

    await history_repo.mark_as_deleted(current_user.id, target_month)

    if target_month == current_month:
        deleted = await repo.delete_by_user_id(current_user.id)
        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "No budget found", "code": "NO_BUDGET"},
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
    """Get current budget progress with spending data for the current month."""
    repo = BudgetRepository(db)
    budget = await repo.get_by_user_id(current_user.id)

    if not budget:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "No budget found", "code": "NO_BUDGET"},
        )

    service = BudgetService(db)
    return await service.get_budget_progress(current_user.id, budget)
