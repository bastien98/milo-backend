import hashlib
import logging
from collections import defaultdict
from datetime import date
from math import ceil
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, UploadFile, File, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_current_db_user
from app.config import get_settings
from app.core.cache import invalidate_user
from app.models.enums import ReceiptStatus
from app.models.user import User

logger = logging.getLogger(__name__)
settings = get_settings()

from app.schemas.receipt import (
    ReceiptUploadAcceptedResponse,
    ReceiptStatusResponse,
    ReceiptUploadResponse,
    ReceiptResponse,
    GroupedReceipt,
    GroupedReceiptTransaction,
    GroupedReceiptListResponse,
    LineItemDeleteResponse,
)
from app.services.receipt_background_worker import process_receipt_background
from app.db.repositories.receipt_repo import ReceiptRepository
from app.db.repositories.transaction_repo import TransactionRepository
from app.core.exceptions import ResourceNotFoundError, DuplicateReceiptError

router = APIRouter()


@router.post("/upload", response_model=ReceiptUploadAcceptedResponse, status_code=202)
async def upload_receipt(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    receipt_date: Optional[date] = Query(None, description="Override receipt date"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
):
    """
    Upload a PDF receipt for async processing.

    Returns immediately with a receipt ID and PENDING status.
    The receipt is processed in the background via Gemini Vision
    for OCR, normalization, and categorization.

    Poll `GET /receipts/{receipt_id}/status` to track processing progress.
    """
    # Validate content type — PDF only
    content_type = file.content_type or "application/octet-stream"
    if content_type != "application/pdf":
        from app.core.exceptions import ImageValidationError
        raise ImageValidationError(
            f"Only PDF files are supported, got: {content_type}",
            details={"supported_types": ["application/pdf"]},
        )

    # Read file bytes now — the UploadFile stream closes with the request
    file_content = await file.read()
    filename = file.filename or "receipt.pdf"
    file_type = "pdf"

    # Compute content hash for duplicate detection
    content_hash = hashlib.sha256(file_content).hexdigest()

    logger.info(
        f"Receipt upload accepted: user_id={current_user.id}, "
        f"filename={filename}, type={file_type}, size={len(file_content)} bytes, "
        f"hash={content_hash[:12]}..."
    )

    # Check for duplicate receipt (global, across all users)
    receipt_repo = ReceiptRepository(db)
    if settings.DUPLICATE_DETECTION_ENABLED:
        existing = await receipt_repo.find_by_content_hash(content_hash)
        if existing:
            raise DuplicateReceiptError(
                "Duplicate receipt detected — this receipt has already been uploaded",
                details={
                    "existing_receipt_id": existing.id,
                    "existing_user_id": existing.user_id,
                    "uploaded_at": existing.created_at.isoformat() if existing.created_at else None,
                },
            )

    # Create receipt record with PENDING status
    receipt = await receipt_repo.create(
        user_id=current_user.id,
        filename=filename,
        file_type=file_type,
        file_size=len(file_content),
        status=ReceiptStatus.PENDING,
        content_hash=content_hash,
    )

    # Commit DB — catch IntegrityError from the unique partial index on content_hash
    # (race condition: two concurrent uploads with the same hash)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise DuplicateReceiptError(
            "Duplicate receipt detected — this receipt has already been uploaded",
            details={"content_hash": content_hash},
        )

    # Schedule background processing — pass PDF bytes directly to Mistral
    background_tasks.add_task(
        process_receipt_background,
        receipt_id=receipt.id,
        user_id=current_user.id,
        file_content=file_content,
        filename=filename,
        receipt_date_override=receipt_date,
    )

    return ReceiptUploadAcceptedResponse(
        receipt_id=receipt.id,
        status=ReceiptStatus.PENDING,
        filename=filename,
    )


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

    The source field indicates whether the receipt was from a scanned receipt
    ("receipt_upload") or a bank import ("bank_import").
    """
    transaction_repo = TransactionRepository(db)
    receipt_repo = ReceiptRepository(db)

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

    # Fetch receipt objects for receipt-level fields
    receipt_map = {}
    if groups:
        receipts, _ = await receipt_repo.get_by_user(
            user_id=current_user.id,
            start_date=start_date,
            end_date=end_date,
            page=1,
            page_size=10000,
        )
        receipt_map = {r.id: r for r in receipts}

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

        # Get receipt-level fields from the receipt object
        receipt_obj = receipt_map.get(receipt_id)

        # Get source from the receipt (default to receipt_upload for backwards compatibility)
        from app.models.enums import ReceiptSource
        source = receipt_obj.source if receipt_obj else ReceiptSource.RECEIPT_UPLOAD

        grouped_receipts.append(
            GroupedReceipt(
                receipt_id=receipt_id,
                store_name=store,
                receipt_date=txn_date,
                receipt_time=receipt_obj.receipt_time if receipt_obj else None,
                total_amount=round(total_amount, 2),
                payment_method=receipt_obj.payment_method if receipt_obj else None,
                total_savings=receipt_obj.total_savings if receipt_obj else None,
                store_branch=receipt_obj.store_branch if receipt_obj else None,
                items_count=items_count,
                average_health_score=average_health_score,
                source=source,
                transactions=[
                    GroupedReceiptTransaction(
                        item_id=t.id,
                        item_name=t.item_name,
                        item_price=t.item_price,
                        quantity=t.quantity,
                        unit_price=t.unit_price,
                        category=t.category,
                        health_score=t.health_score,
                        normalized_name=t.normalized_name,
                        normalized_brand=t.normalized_brand,
                        is_discount=t.is_discount,
                        is_deposit=t.is_deposit,
                        granular_category=t.granular_category,
                        unit_of_measure=t.unit_of_measure,
                        weight_or_volume=t.weight_or_volume,
                        price_per_unit_measure=t.price_per_unit_measure,
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


@router.get("/{receipt_id}/status", response_model=ReceiptStatusResponse)
async def get_receipt_status(
    receipt_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
):
    """Poll receipt processing status.

    Returns the current processing state along with the filename
    (for persistent UI display) and detected_date once completed
    (so the frontend knows which period to refresh).
    """
    receipt_repo = ReceiptRepository(db)

    receipt = await receipt_repo.get_by_id_and_user(
        receipt_id=receipt_id,
        user_id=current_user.id,
    )

    if not receipt:
        raise ResourceNotFoundError(f"Receipt {receipt_id} not found")

    # Count transactions if processing is complete
    items_count = 0
    if receipt.status == ReceiptStatus.COMPLETED:
        transaction_repo = TransactionRepository(db)
        transactions = await transaction_repo.get_by_receipt(receipt_id)
        items_count = len(transactions)

    return ReceiptStatusResponse(
        receipt_id=receipt.id,
        status=receipt.status,
        filename=receipt.original_filename,
        detected_date=receipt.receipt_date,
        store_name=receipt.store_name,
        total_amount=receipt.total_amount,
        items_count=items_count,
        error_message=receipt.error_message,
        error_code=receipt.error_code,
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
    invalidate_user(current_user.id)

    return {"message": "Receipt deleted successfully"}


@router.delete("/{receipt_id}/items/{item_id}", response_model=LineItemDeleteResponse)
async def delete_line_item(
    receipt_id: str,
    item_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
):
    """
    Delete a single line item from a receipt.

    This will:
    - Remove the item from the receipt
    - Recalculate the receipt's total_amount, items_count, and average_health_score
    - If this was the last item, the entire receipt will be deleted

    Returns the updated receipt totals after deletion.
    """
    receipt_repo = ReceiptRepository(db)
    transaction_repo = TransactionRepository(db)

    # Verify receipt ownership
    receipt = await receipt_repo.get_by_id_and_user(
        receipt_id=receipt_id,
        user_id=current_user.id,
    )

    if not receipt:
        raise ResourceNotFoundError(f"Receipt {receipt_id} not found")

    # Get the transaction and verify it belongs to this receipt
    transaction = await transaction_repo.get_by_id_and_user(
        transaction_id=item_id,
        user_id=current_user.id,
    )

    if not transaction:
        raise ResourceNotFoundError(f"Item {item_id} not found")

    if transaction.receipt_id != receipt_id:
        raise ResourceNotFoundError(f"Item {item_id} not found in receipt {receipt_id}")

    # Get all transactions for this receipt to calculate new totals
    all_transactions = await transaction_repo.get_by_receipt(receipt_id)

    # Check if this is the last item
    if len(all_transactions) <= 1:
        # Delete the entire receipt (cascade will delete the transaction)
        await receipt_repo.delete(receipt_id)

        return LineItemDeleteResponse(
            success=True,
            message="Last item deleted - receipt removed",
            updated_total_amount=0.0,
            updated_items_count=0,
            updated_average_health_score=None,
            receipt_deleted=True,
        )

    # Delete the transaction
    await transaction_repo.delete(item_id)

    # Calculate new totals (excluding the deleted item)
    remaining_transactions = [t for t in all_transactions if t.id != item_id]

    new_total_amount = sum(t.item_price for t in remaining_transactions)
    new_items_count = len(remaining_transactions)

    # Calculate new average health score (excluding nulls)
    health_scores = [t.health_score for t in remaining_transactions if t.health_score is not None]
    new_average_health_score = (
        round(sum(health_scores) / len(health_scores), 1)
        if health_scores
        else None
    )

    # Update the receipt with new total
    await receipt_repo.update(
        receipt_id=receipt_id,
        total_amount=round(new_total_amount, 2),
    )
    invalidate_user(current_user.id)

    return LineItemDeleteResponse(
        success=True,
        message="Item deleted successfully",
        updated_total_amount=round(new_total_amount, 2),
        updated_items_count=new_items_count,
        updated_average_health_score=new_average_health_score,
        receipt_deleted=False,
    )
