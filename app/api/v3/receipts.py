from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, UploadFile, File, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_current_db_user
from app.models.user import User
from app.schemas.receipt import ReceiptUploadResponse
from app.services.receipt_processor_v3 import ReceiptProcessorV3
from app.db.repositories.receipt_repo import ReceiptRepository
from app.db.repositories.transaction_repo import TransactionRepository

router = APIRouter()


@router.post("/upload", response_model=ReceiptUploadResponse)
async def upload_receipt(
    file: UploadFile = File(...),
    receipt_date: Optional[date] = Query(None, description="Override receipt date"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
):
    """
    Upload and process a receipt using Veryfi OCR and Claude categorization.

    This v3 endpoint uses:
    - Veryfi API for OCR extraction (item names, prices, quantities)
    - Claude API for categorization and health scoring

    Accepts PDF, JPG, or PNG files.
    Returns the extracted data synchronously.
    """
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

    return result
