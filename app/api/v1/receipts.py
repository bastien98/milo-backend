import logging
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, UploadFile, File, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_current_db_user
from app.models.user import User
from app.schemas.receipt import ReceiptUploadResponse, ReceiptResponse, ReceiptListResponse
from app.services.receipt_processor_v2 import ReceiptProcessorV2
from app.db.repositories.receipt_repo import ReceiptRepository
from app.db.repositories.transaction_repo import TransactionRepository
from app.core.exceptions import ResourceNotFoundError
from app.services.enriched_profile_service import EnrichedProfileService

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("", response_model=ReceiptListResponse)
async def list_receipts(
    start_date: Optional[date] = Query(None, description="Filter by start date (receipt date)"),
    end_date: Optional[date] = Query(None, description="Filter by end date (receipt date)"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
):
    """
    List receipts for the current user with optional date filtering.

    Filters by receipt_date (the date on the receipt), not created_at (upload date).
    Date filtering is inclusive: receipts where start_date <= receipt_date <= end_date.
    """
    receipt_repo = ReceiptRepository(db)

    receipts, total = await receipt_repo.get_by_user(
        user_id=current_user.id,
        start_date=start_date,
        end_date=end_date,
        page=page,
        page_size=page_size,
    )

    return ReceiptListResponse(
        receipts=[ReceiptResponse.model_validate(r) for r in receipts],
        total=total,
        page=page,
        page_size=page_size,
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

    # Rebuild enriched profile after deletion
    await EnrichedProfileService.rebuild_profile(current_user.id, db)

    return {"message": "Receipt deleted successfully"}


@router.post("/upload", response_model=ReceiptUploadResponse)
async def upload_receipt(
    file: UploadFile = File(...),
    receipt_date: Optional[date] = Query(None, description="Override receipt date"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
):
    """
    Upload and process a receipt using Veryfi OCR and Gemini categorization.

    This endpoint uses:
    - Veryfi API for OCR extraction (item names, prices, quantities)
    - Gemini API for categorization and health scoring

    Accepts PDF, JPG, or PNG files.
    Returns the extracted data synchronously.

    **Duplicate Detection**: If Veryfi detects this receipt was previously processed,
    returns `is_duplicate: true` with empty `receipt_id` and no transactions saved.
    """
    logger.info(
        f"Receipt upload: user_id={current_user.id}, "
        f"receipt_date_override={receipt_date}"
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

    logger.info(
        f"Receipt upload complete: user_id={current_user.id}, receipt_id={result.receipt_id}, "
        f"items_count={result.items_count}"
    )

    # Rebuild enriched profile with updated transaction data (also invalidates cache)
    if not result.is_duplicate:
        await EnrichedProfileService.rebuild_profile(current_user.id, db)

    return result
