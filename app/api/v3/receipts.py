import logging
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, UploadFile, File, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_current_db_user
from app.core.security import get_current_user, FirebaseUser
from app.models.user import User
from app.schemas.receipt import ReceiptUploadResponse, ReceiptDeleteResponse, ReceiptRateLimitInfo
from app.services.receipt_processor_v3 import ReceiptProcessorV3
from app.services.rate_limit_service import RateLimitService
from app.db.repositories.receipt_repo import ReceiptRepository
from app.db.repositories.transaction_repo import TransactionRepository
from app.core.exceptions import RateLimitExceededError, ResourceNotFoundError

logger = logging.getLogger(__name__)

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
    Upload and process a receipt using Veryfi OCR and Claude categorization.

    This v3 endpoint uses:
    - Veryfi API for OCR extraction (item names, prices, quantities)
    - Claude API for categorization and health scoring

    Rate limited to 15 uploads per month.

    Accepts PDF, JPG, or PNG files.
    Returns the extracted data synchronously.
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

    processor = ReceiptProcessorV3(
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


@router.delete("/{receipt_id}", response_model=ReceiptDeleteResponse)
async def delete_receipt(
    receipt_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
    firebase_user: FirebaseUser = Depends(get_current_user),
):
    """
    Delete a receipt and all its associated transactions.

    The authenticated user must own the receipt to delete it.
    Note: Deleting a receipt does not restore the upload credit.
    """
    logger.info(f"DELETE receipt request - receipt_id: {receipt_id}, user_id: {current_user.id}, firebase_uid: {firebase_user.uid}")

    receipt_repo = ReceiptRepository(db)
    rate_limit_service = RateLimitService(db)

    # Verify ownership - get_by_id_and_user returns None if not found or not owned
    receipt = await receipt_repo.get_by_id_and_user(
        receipt_id=receipt_id,
        user_id=current_user.id,
    )

    logger.info(f"Receipt lookup result - found: {receipt is not None}, receipt_id: {receipt_id}, user_id: {current_user.id}")

    if not receipt:
        logger.warning(f"Receipt not found - receipt_id: {receipt_id}, user_id: {current_user.id}")
        raise ResourceNotFoundError(
            message="No receipt found with the specified ID"
        )

    # Delete the receipt (transactions are cascade deleted via the model relationship)
    await receipt_repo.delete(receipt_id)
    logger.info(f"Receipt deleted successfully - receipt_id: {receipt_id}, user_id: {current_user.id}")

    # Get current rate limit status
    rate_limit_status = await rate_limit_service.get_receipt_status(firebase_user.uid)

    return ReceiptDeleteResponse(
        success=True,
        message="Receipt deleted successfully",
        deleted_receipt_id=receipt_id,
        rate_limit=ReceiptRateLimitInfo(
            receipts_used=rate_limit_status.receipts_used,
            receipts_limit=rate_limit_status.receipts_limit,
            period_end_date=rate_limit_status.period_end_date,
        ),
    )


@router.get("/{receipt_id}")
async def get_receipt(
    receipt_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
):
    """
    Get a specific receipt by ID (for debugging).
    """
    logger.info(f"GET receipt request - receipt_id: {receipt_id}, user_id: {current_user.id}")

    receipt_repo = ReceiptRepository(db)
    receipt = await receipt_repo.get_by_id_and_user(
        receipt_id=receipt_id,
        user_id=current_user.id,
    )

    if not receipt:
        logger.warning(f"Receipt not found - receipt_id: {receipt_id}, user_id: {current_user.id}")
        raise ResourceNotFoundError(
            message="No receipt found with the specified ID"
        )

    return {
        "id": receipt.id,
        "user_id": receipt.user_id,
        "status": receipt.status.value,
        "store_name": receipt.store_name,
        "created_at": receipt.created_at.isoformat() if receipt.created_at else None,
    }
