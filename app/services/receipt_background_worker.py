"""Background worker for async receipt processing.

Runs outside the request lifecycle with its own DB session.
Called via FastAPI BackgroundTasks from the upload endpoint.
"""

import asyncio
import logging
import time
from datetime import date, datetime, timezone
from datetime import time as dt_time
from typing import Optional

from app.db.session import async_session_maker
from app.db.repositories.receipt_repo import ReceiptRepository
from app.db.repositories.transaction_repo import TransactionRepository
from app.models.transaction import Transaction
from app.models.enums import ReceiptStatus
from app.core.stores import resolve_store_name
from app.services.gemini_vision_service import GeminiVisionService
from app.core.cache import invalidate_user

logger = logging.getLogger(__name__)


async def process_receipt_background(
    receipt_id: str,
    user_id: str,
    file_content: bytes,
    filename: str,
    receipt_date_override: Optional[date] = None,
) -> None:
    """Process a receipt in the background.

    Creates its own DB session since the request session is closed
    by the time this runs. All exceptions are caught and recorded
    as FAILED status on the receipt.

    Sends PDF bytes directly to Gemini Vision — no S3 needed.
    """
    task_start = time.monotonic()
    logger.info(
        f"Background processing started: receipt_id={receipt_id}, "
        f"user_id={user_id}, filename={filename}, "
        f"size={len(file_content)} bytes"
    )

    async with async_session_maker() as session:
        try:
            receipt_repo = ReceiptRepository(session)
            transaction_repo = TransactionRepository(session)

            # Step 1: Mark as PROCESSING
            t0 = time.monotonic()
            await receipt_repo.update(
                receipt_id=receipt_id,
                status=ReceiptStatus.PROCESSING,
            )
            await session.commit()
            logger.info(f"⏱ bg_mark_processing: {time.monotonic() - t0:.3f}s")

            # Step 2: Upload PDF to Gemini Files API and extract (15 min max)
            t0 = time.monotonic()
            gemini_service = GeminiVisionService()
            try:
                extraction_result = await asyncio.wait_for(
                    gemini_service.extract_receipt(file_content, user_id=user_id),
                    timeout=900,
                )
            except asyncio.TimeoutError:
                raise Exception("Receipt processing timed out after 15 minutes")
            logger.info(
                f"⏱ bg_gemini_extraction: {time.monotonic() - t0:.3f}s - "
                f"vendor={extraction_result.vendor_name}, "
                f"items={len(extraction_result.line_items)}"
            )

            # Step 3: Resolve store name (fallback to "other" if unknown)
            t0 = time.monotonic()
            canonical_store = resolve_store_name(extraction_result.vendor_name)
            if canonical_store is None:
                logger.warning(
                    f"Unknown store '{extraction_result.vendor_name}' for "
                    f"receipt {receipt_id}, using 'other'"
                )
                canonical_store = "other"
            cleaned_store_name = canonical_store
            logger.info(f"⏱ bg_store_resolution: {time.monotonic() - t0:.3f}s")

            # Step 4: Create transactions (batch insert — single flush)
            t0 = time.monotonic()
            final_date = receipt_date_override or extraction_result.receipt_date
            txn_date = final_date or date.today()

            transactions = [
                Transaction(
                    user_id=user_id,
                    receipt_id=receipt_id,
                    store_name=cleaned_store_name,
                    item_name=item.item_name,
                    item_price=item.total_price,
                    quantity=item.quantity,
                    unit_price=item.unit_price,
                    category=item.parent_category,
                    date=txn_date,
                    normalized_name=item.normalized_name,
                    normalized_brand=item.normalized_brand,
                    is_premium=item.is_premium,
                    is_discount=item.is_discount,
                    is_deposit=item.is_deposit,
                    granular_category=item.granular_category,
                    unit_of_measure=item.unit_of_measure,
                    weight_or_volume=item.weight_or_volume,
                    price_per_unit_measure=item.price_per_unit_measure,
                    dp_expanded_description=item.dp_expanded_description,
                    dp_pack_quantity=item.dp_pack_quantity,
                    dp_pack_size=item.dp_pack_size,
                    dp_pack_unit=item.dp_pack_unit,
                    dp_product_variant=item.dp_product_variant,
                    dp_article_code=item.dp_article_code,
                    dp_is_bio=item.dp_is_bio,
                    lookup_key=item.lookup_key,
                )
                for item in extraction_result.line_items
            ]
            await transaction_repo.create_batch(transactions)
            logger.info(
                f"bg_create_transactions: {time.monotonic() - t0:.3f}s "
                f"({len(extraction_result.line_items)} items)"
            )

            # Step 5: Compute final total
            if extraction_result.total and extraction_result.total > 0:
                final_total = extraction_result.total
            else:
                final_total = sum(
                    item.total_price for item in extraction_result.line_items
                )

            # Parse receipt_time
            parsed_receipt_time = None
            if extraction_result.receipt_time:
                try:
                    parts = extraction_result.receipt_time.split(":")
                    parsed_receipt_time = dt_time(int(parts[0]), int(parts[1]))
                except (ValueError, IndexError):
                    pass

            # Step 6: Update receipt to COMPLETED + invalidate cache
            t0 = time.monotonic()
            await receipt_repo.update(
                receipt_id=receipt_id,
                status=ReceiptStatus.COMPLETED,
                store_name=cleaned_store_name,
                receipt_date=final_date,
                total_amount=final_total,
                processed_at=datetime.now(timezone.utc),
                receipt_time=parsed_receipt_time,
                payment_method=extraction_result.payment_method,
                total_savings=extraction_result.total_savings,
                store_branch=extraction_result.store_branch,
            )
            await session.commit()
            invalidate_user(user_id)
            logger.info(f"⏱ bg_mark_completed: {time.monotonic() - t0:.3f}s")

            logger.info(
                f"⏱ bg_total: {time.monotonic() - task_start:.3f}s — "
                f"receipt_id={receipt_id}, store={cleaned_store_name}, "
                f"items={len(extraction_result.line_items)}"
            )

        except Exception as e:
            logger.error(
                f"Background processing failed: receipt_id={receipt_id}, "
                f"elapsed={time.monotonic() - task_start:.3f}s, error={e}",
                exc_info=True,
            )
            await session.rollback()
            try:
                await receipt_repo.update(
                    receipt_id=receipt_id,
                    status=ReceiptStatus.FAILED,
                    error_message=str(e),
                )
                await session.commit()
            except Exception as update_err:
                logger.error(
                    f"Failed to update receipt status to FAILED: "
                    f"receipt_id={receipt_id}, error={update_err}"
                )
                await session.rollback()
