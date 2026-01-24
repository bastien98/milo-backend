from collections import defaultdict
from datetime import date
from math import ceil
from typing import Optional

from fastapi import APIRouter, Depends, UploadFile, File, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_current_db_user
from app.core.security import get_current_user, FirebaseUser
from app.models.user import User
from app.schemas.receipt import (
    ReceiptUploadResponse,
    ReceiptResponse,
    GroupedReceipt,
    GroupedReceiptTransaction,
    GroupedReceiptListResponse,
)
from app.services.receipt_processor_v2 import ReceiptProcessorV2
from app.services.rate_limit_service import RateLimitService
from app.db.repositories.receipt_repo import ReceiptRepository
from app.db.repositories.transaction_repo import TransactionRepository
from app.core.exceptions import ResourceNotFoundError, RateLimitExceededError

router = APIRouter()


@router.post("/upload", response_model=ReceiptUploadResponse)
async def upload_receipt(
    file: UploadFile = File(...),
    receipt_date: Optional[date] = Query(None, description="Override receipt date"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
    firebase_user: FirebaseUser = Depends(get_current_user),
):
    """
    Upload and process a receipt.

    Accepts PDF, JPG, or PNG files. The receipt will be analyzed using
    Veryfi for OCR and Google Gemini for categorization.

    Rate limited to 15 uploads per month.

    Returns the extracted data synchronously.

    **Duplicate Detection**: If Veryfi detects this receipt was previously processed,
    returns `is_duplicate: true` with empty `receipt_id` and no transactions saved.
    """
    # Check receipt upload rate limit
    rate_limit_service = RateLimitService(db)
    rate_limit_status = await rate_limit_service.check_receipt_rate_limit(firebase_user.uid)

    if not rate_limit_status.allowed:
        raise RateLimitExceededError(
            message=f"Receipt upload limit exceeded. You have used {rate_limit_status.receipts_used}/{rate_limit_status.receipts_limit} uploads this month.",
            details={
                "receipts_used": rate_limit_status.receipts_used,
                "receipts_limit": rate_limit_status.receipts_limit,
                "period_end_date": rate_limit_status.period_end_date.isoformat(),
                "retry_after_seconds": rate_limit_status.retry_after_seconds,
            },
        )

    receipt_repo = ReceiptRepository(db)
    transaction_repo = TransactionRepository(db)

    processor = ReceiptProcessorV2(
        receipt_repo=receipt_repo,
        transaction_repo=transaction_repo,
    )

    result = await processor.process_receipt(
        user_id=current_user.id,
        file=file,
        receipt_date_override=receipt_date,
    )

    # Increment the rate limit counter after successful upload
    await rate_limit_status.increment_on_success()

    return result


@router.get("", response_model=GroupedReceiptListResponse)
async def list_receipts(
    start_date: Optional[date] = Query(None, description="Filter by start date (YYYY-MM-DD)"),
    end_date: Optional[date] = Query(None, description="Filter by end date (YYYY-MM-DD)"),
    store_name: Optional[str] = Query(None, description="Filter by store name"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
):
    """
    List receipts with their transactions.

    Returns receipts sorted by date descending.
    Each receipt contains all transactions from a single uploaded receipt.

    The receipt_id returned is the actual database UUID, which can be used
    directly with DELETE /api/v2/receipts/{receipt_id}.
    """
    transaction_repo = TransactionRepository(db)

    # Fetch all matching transactions (without pagination - we paginate groups)
    transactions, _ = await transaction_repo.get_by_user(
        user_id=current_user.id,
        start_date=start_date,
        end_date=end_date,
        store_name=store_name,
        page=1,
        page_size=10000,  # Large enough to get all for grouping
    )

    # Group transactions by receipt_id (the actual database UUID)
    # Skip transactions without a receipt_id (shouldn't happen for receipt-based transactions)
    groups: dict[str, list] = defaultdict(list)
    for txn in transactions:
        if txn.receipt_id:
            groups[txn.receipt_id].append(txn)

    # Build grouped receipts
    grouped_receipts = []
    for receipt_id, txns in groups.items():
        # Get store_name and date from the first transaction (should be consistent within a receipt)
        first_txn = txns[0]
        store = first_txn.store_name
        txn_date = first_txn.date

        total_amount = sum(t.item_price for t in txns)
        items_count = len(txns)

        # Calculate average health score (excluding nulls)
        health_scores = [t.health_score for t in txns if t.health_score is not None]
        average_health_score = (
            round(sum(health_scores) / len(health_scores), 1)
            if health_scores
            else None
        )

        grouped_receipts.append(
            GroupedReceipt(
                receipt_id=receipt_id,
                store_name=store,
                receipt_date=txn_date,
                total_amount=round(total_amount, 2),
                items_count=items_count,
                average_health_score=average_health_score,
                transactions=[
                    GroupedReceiptTransaction(
                        item_name=t.item_name,
                        item_price=t.item_price,
                        quantity=t.quantity,
                        unit_price=t.unit_price,
                        category=t.category,
                        health_score=t.health_score,
                    )
                    for t in txns
                ],
            )
        )

    # Sort by date descending (most recent first)
    grouped_receipts.sort(key=lambda r: r.receipt_date, reverse=True)

    # Apply pagination to grouped receipts
    total = len(grouped_receipts)
    total_pages = ceil(total / page_size) if total > 0 else 1
    offset = (page - 1) * page_size
    paginated_receipts = grouped_receipts[offset : offset + page_size]

    return GroupedReceiptListResponse(
        receipts=paginated_receipts,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get("/{receipt_id}", response_model=ReceiptResponse)
async def get_receipt(
    receipt_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
):
    """Get a specific receipt by ID."""
    receipt_repo = ReceiptRepository(db)

    receipt = await receipt_repo.get_by_id_and_user(
        receipt_id=receipt_id,
        user_id=current_user.id,
    )

    if not receipt:
        raise ResourceNotFoundError(f"Receipt {receipt_id} not found")

    return ReceiptResponse.model_validate(receipt)


@router.delete("/{receipt_id}")
async def delete_receipt(
    receipt_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
):
    """Delete a receipt and all its transactions."""
    receipt_repo = ReceiptRepository(db)

    # Verify ownership
    receipt = await receipt_repo.get_by_id_and_user(
        receipt_id=receipt_id,
        user_id=current_user.id,
    )

    if not receipt:
        raise ResourceNotFoundError(f"Receipt {receipt_id} not found")

    await receipt_repo.delete(receipt_id)

    return {"message": "Receipt deleted successfully"}
