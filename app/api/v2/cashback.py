from math import ceil

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_current_db_user
from app.models.user import User
from app.services.cashback_service import CashbackService
from app.schemas.cashback import (
    CashbackBalanceResponse,
    CashbackSummaryResponse,
    CashbackHistoryResponse,
    CashbackTransactionResponse,
    CashbackCalculationPreview,
    CashbackSegment,
)

router = APIRouter()


@router.get("/balance", response_model=CashbackBalanceResponse)
async def get_balance(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
):
    """Get the user's current cashback wallet balance."""
    svc = CashbackService(db)
    balance = await svc.get_balance(current_user.id)
    return CashbackBalanceResponse.model_validate(balance)


@router.get("/summary", response_model=CashbackSummaryResponse)
async def get_summary(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
):
    """Get cashback summary: balance, recent transactions, and stats."""
    svc = CashbackService(db)

    balance = await svc.get_balance(current_user.id)
    transactions, total = await svc.get_transaction_history(
        current_user.id, page=1, page_size=5
    )

    # Build response with store_name/receipt_date from the receipt relationship
    recent = []
    for txn in transactions:
        receipt = txn.receipt
        recent.append(
            CashbackTransactionResponse(
                id=txn.id,
                receipt_id=txn.receipt_id,
                receipt_total=txn.receipt_total,
                cashback_amount=txn.cashback_amount,
                effective_rate=txn.effective_rate,
                status=txn.status,
                created_at=txn.created_at,
                store_name=receipt.store_name if receipt else None,
                receipt_date=receipt.receipt_date if receipt else None,
            )
        )

    avg_cashback = (
        round(balance.total_earned / total, 2) if total > 0 else 0.0
    )

    return CashbackSummaryResponse(
        balance=CashbackBalanceResponse.model_validate(balance),
        recent_transactions=recent,
        avg_cashback_per_receipt=avg_cashback,
        total_receipts_with_cashback=total,
    )


@router.get("/history", response_model=CashbackHistoryResponse)
async def get_history(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
):
    """Get paginated cashback transaction history."""
    svc = CashbackService(db)
    transactions, total = await svc.get_transaction_history(
        current_user.id, page=page, page_size=page_size
    )

    items = []
    for txn in transactions:
        receipt = txn.receipt
        items.append(
            CashbackTransactionResponse(
                id=txn.id,
                receipt_id=txn.receipt_id,
                receipt_total=txn.receipt_total,
                cashback_amount=txn.cashback_amount,
                effective_rate=txn.effective_rate,
                status=txn.status,
                created_at=txn.created_at,
                store_name=receipt.store_name if receipt else None,
                receipt_date=receipt.receipt_date if receipt else None,
            )
        )

    total_pages = ceil(total / page_size) if total > 0 else 1

    return CashbackHistoryResponse(
        transactions=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get("/preview", response_model=CashbackCalculationPreview)
async def preview_cashback(
    amount: float = Query(..., gt=0, description="Receipt total to preview"),
    current_user: User = Depends(get_current_db_user),
):
    """Preview cashback calculation for a given receipt amount."""
    cashback_amount, effective_rate = CashbackService.calculate_cashback(amount)
    segments = CashbackService.calculate_cashback_segments(amount)

    return CashbackCalculationPreview(
        receipt_total=amount,
        cashback_amount=cashback_amount,
        effective_rate=effective_rate,
        segments=[CashbackSegment(**s) for s in segments],
    )
