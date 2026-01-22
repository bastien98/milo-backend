from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, UploadFile, File, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_current_db_user
from app.core.security import get_current_user, FirebaseUser
from app.models.user import User
from app.schemas.receipt import ReceiptUploadResponse
from app.services.receipt_processor_v3 import ReceiptProcessorV3
from app.services.rate_limit_service import RateLimitService
from app.db.repositories.receipt_repo import ReceiptRepository
from app.db.repositories.transaction_repo import TransactionRepository
from app.core.exceptions import RateLimitExceededError

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
