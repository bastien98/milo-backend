from datetime import datetime, date
from dateutil.relativedelta import relativedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_current_db_user
from app.models.user import User
from app.db.repositories.budget_repo import BudgetRepository
from app.db.repositories.budget_history_repo import BudgetHistoryRepository
from app.db.repositories.budget_ai_insight_repo import BudgetAIInsightRepository
from app.services.budget_service import BudgetService
from app.services.budget_ai_service import BudgetAIService
from app.core.exceptions import GeminiAPIError
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
from app.schemas.budget_ai import (
    AIBudgetSuggestionResponse,
    AICheckInResponse,
    AIReceiptAnalysisRequest,
    AIReceiptAnalysisResponse,
    AIMonthlyReportResponse,
    AIInsightFeedbackRequest,
    AIInsightFeedbackResponse,
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
    current_user: User = Depends(get_current_db_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Delete the user's budget.

    This marks the budget as deleted in history (prevents auto-rollover)
    and removes it from the active budgets table.

    Returns:
    - 204: Budget deleted successfully (no content)
    - 401: Invalid or missing authentication token
    - 404: No budget found
    """
    repo = BudgetRepository(db)
    history_repo = BudgetHistoryRepository(db)

    # Mark budget as deleted in history for current month
    current_month = date.today().strftime("%Y-%m")
    await history_repo.mark_as_deleted(current_user.id, current_month)

    # Delete from active budgets table
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
    response_model=AIBudgetSuggestionResponse,
    responses={
        404: {"description": "No spending history found"},
        503: {"description": "AI service temporarily unavailable"},
    },
)
async def get_ai_budget_suggestion(
    months: int = Query(
        default=3,
        ge=1,
        le=12,
        description="Number of months to analyze",
    ),
    target_amount: float | None = Query(
        default=None,
        gt=0,
        description="Optional target budget amount. When provided, AI will intelligently "
        "allocate categories to fit this budget, prioritizing cuts to high savings "
        "potential categories while preserving essentials.",
    ),
    current_user: User = Depends(get_current_db_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Generate an AI-powered budget recommendation with personalized insights.

    Uses AI to analyze spending patterns and provide:
    - Recommended monthly budget
    - Category allocations with reasoning
    - Savings opportunities
    - Spending insights and patterns
    - Personalized tips
    - Budget health score

    When target_amount is provided:
    - AI intelligently recalculates category allocations to fit the target
    - Prioritizes cutting categories with high savings potential
    - Preserves essential categories (Fresh Produce, Dairy)
    - Returns allocation_strategy explaining the approach
    - Budget health score reflects achievability of the target

    Returns:
    - 200: AI budget suggestion
    - 401: Invalid or missing authentication token
    - 404: No spending history found
    - 503: AI service temporarily unavailable
    """
    try:
        ai_service = BudgetAIService()
        result = await ai_service.generate_budget_suggestion(
            db, current_user.id, months, target_amount=target_amount
        )
        return result

    except GeminiAPIError as e:
        if "no_data" in str(e.details.get("error_type", "")):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "error": "No spending history found",
                    "code": "NO_HISTORY",
                },
            )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "AI service temporarily unavailable",
                "code": "AI_ERROR",
                "message": str(e.message),
            },
        )


@router.get(
    "/ai-check-in",
    response_model=AICheckInResponse,
    responses={
        404: {"description": "No budget found"},
        503: {"description": "AI service temporarily unavailable"},
    },
)
async def get_ai_checkin(
    current_user: User = Depends(get_current_db_user),
    db: AsyncSession = Depends(get_db),
):
    """
    AI check-in on budget progress.

    Provides a friendly, encouraging analysis of current month progress:
    - Personalized greeting based on status
    - Status summary with emoji
    - Daily budget remaining
    - Projected end-of-month spending
    - Focus areas needing attention
    - Weekly tip
    - Motivational message

    Returns:
    - 200: AI check-in response
    - 401: Invalid or missing authentication token
    - 404: No budget found
    - 503: AI service temporarily unavailable
    """
    insight_repo = BudgetAIInsightRepository(db)

    # Generate check-in
    try:
        ai_service = BudgetAIService()
        result = await ai_service.generate_checkin(db, current_user.id)

        # Store the insight
        await insight_repo.create(
            user_id=current_user.id,
            insight_type="checkin",
            ai_response=result.model_dump(),
            model_used=ai_service.MODEL,
        )

        # Clean up old check-ins (keep last 30)
        await insight_repo.delete_old_insights(current_user.id, "checkin", keep_count=30)

        return result

    except GeminiAPIError as e:
        if "no_budget" in str(e.details.get("error_type", "")):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "error": "No budget found",
                    "code": "NO_BUDGET",
                },
            )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "AI service temporarily unavailable",
                "code": "AI_ERROR",
                "message": str(e.message),
            },
        )


@router.post(
    "/ai-analyze-receipt",
    response_model=AIReceiptAnalysisResponse,
    responses={
        404: {"description": "Receipt not found"},
        503: {"description": "AI service temporarily unavailable"},
    },
)
async def analyze_receipt_ai(
    request: AIReceiptAnalysisRequest,
    current_user: User = Depends(get_current_db_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Instant AI feedback on a scanned receipt.

    Analyzes a receipt in context of the user's budget and provides:
    - Impact summary
    - Status indicator (great/fine/caution/warning)
    - Notable items
    - Quick tip (if relevant)
    - Budget remaining after this receipt

    No caching - provides real-time analysis.

    Returns:
    - 200: AI receipt analysis
    - 401: Invalid or missing authentication token
    - 404: Receipt not found or doesn't belong to user
    - 503: AI service temporarily unavailable
    """
    try:
        ai_service = BudgetAIService()
        result = await ai_service.analyze_receipt(
            db, current_user.id, request.receipt_id
        )

        # Optionally store for history (but don't cache)
        insight_repo = BudgetAIInsightRepository(db)
        await insight_repo.create(
            user_id=current_user.id,
            insight_type="receipt_analysis",
            ai_response=result.model_dump(),
            model_used=ai_service.MODEL,
            receipt_id=request.receipt_id,
        )

        # Clean up old receipt analyses (keep last 50)
        await insight_repo.delete_old_insights(
            current_user.id, "receipt_analysis", keep_count=50
        )

        return result

    except GeminiAPIError as e:
        if "not_found" in str(e.details.get("error_type", "")):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "error": "Receipt not found",
                    "code": "NOT_FOUND",
                },
            )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "AI service temporarily unavailable",
                "code": "AI_ERROR",
                "message": str(e.message),
            },
        )


@router.get(
    "/ai-month-report",
    response_model=AIMonthlyReportResponse,
    responses={
        404: {"description": "No receipts found for this month"},
        503: {"description": "AI service temporarily unavailable"},
    },
)
async def get_ai_monthly_report(
    month: str = Query(
        ...,
        pattern=r"^\d{4}-\d{2}$",
        description="Month in YYYY-MM format (e.g., 2026-01)",
    ),
    current_user: User = Depends(get_current_db_user),
    db: AsyncSession = Depends(get_db),
):
    """
    End-of-month AI summary and report.

    Generates a comprehensive monthly report with:
    - Catchy headline summary
    - Overall grade and score
    - Wins and challenges
    - Category-by-category grades
    - Spending trends
    - Next month focus recommendations
    - Fun stats

    Reports for completed months are cached permanently.

    Returns:
    - 200: AI monthly report
    - 401: Invalid or missing authentication token
    - 404: No receipts found for this month
    - 503: AI service temporarily unavailable
    """
    insight_repo = BudgetAIInsightRepository(db)

    # Check if this is a past month (complete)
    from datetime import date
    year, month_num = map(int, month.split("-"))
    today = date.today()
    is_past_month = (year < today.year) or (year == today.year and month_num < today.month)

    # Check cache for past months
    if is_past_month:
        cached = await insight_repo.get_monthly_report(current_user.id, month)
        if cached and cached.ai_response:
            return AIMonthlyReportResponse(**cached.ai_response)

    # Generate report
    try:
        ai_service = BudgetAIService()
        result = await ai_service.generate_monthly_report(db, current_user.id, month)

        # Cache the result (especially for past months)
        await insight_repo.create(
            user_id=current_user.id,
            insight_type="monthly_report",
            month=month,
            ai_response=result.model_dump(),
            model_used=ai_service.MODEL,
        )

        return result

    except GeminiAPIError as e:
        if "no_data" in str(e.details.get("error_type", "")):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "error": "No receipts found for this month",
                    "code": "NO_DATA",
                },
            )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "AI service temporarily unavailable",
                "code": "AI_ERROR",
                "message": str(e.message),
            },
        )


@router.post(
    "/ai-feedback",
    response_model=AIInsightFeedbackResponse,
    status_code=status.HTTP_201_CREATED,
)
async def submit_ai_feedback(
    request: AIInsightFeedbackRequest,
    current_user: User = Depends(get_current_db_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Submit feedback on an AI insight.

    Helps improve AI recommendations by tracking user feedback.

    Returns:
    - 201: Feedback submitted successfully
    - 401: Invalid or missing authentication token
    - 404: Insight not found
    """
    insight_repo = BudgetAIInsightRepository(db)

    # Verify insight exists
    insight = await insight_repo.get_by_id(request.insight_id)
    if not insight or insight.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "Insight not found",
                "code": "NOT_FOUND",
            },
        )

    # Add feedback
    feedback = await insight_repo.add_feedback(
        insight_id=request.insight_id,
        user_id=current_user.id,
        feedback_type=request.feedback_type,
    )

    return AIInsightFeedbackResponse(
        id=feedback.id,
        insight_id=feedback.insight_id,
        feedback_type=feedback.feedback_type,
        created_at=feedback.created_at,
    )
