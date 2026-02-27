"""Background worker for async receipt processing.

Runs outside the request lifecycle with its own DB session.
Called via FastAPI BackgroundTasks from the upload endpoint.
"""

import hashlib
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
from app.core.exceptions import UnsupportedStoreError
from app.core.stores import resolve_store_name
from app.services.image_validator import ImageValidator
from app.services.mistral_document_service import MistralDocumentService
from app.services.enriched_profile_service import EnrichedProfileService

logger = logging.getLogger(__name__)


async def process_receipt_background(
    receipt_id: str,
    user_id: str,
    file_content: bytes,
    content_type: str,
    filename: str,
    file_type: str,
    receipt_date_override: Optional[date] = None,
) -> None:
    """Process a receipt in the background.

    Creates its own DB session since the request session is closed
    by the time this runs. All exceptions are caught and recorded
    as FAILED status on the receipt.
    """
    logger.info(
        f"Background processing started: receipt_id={receipt_id}, "
        f"user_id={user_id}, filename={filename}"
    )

    async with async_session_maker() as session:
        try:
            receipt_repo = ReceiptRepository(session)
            transaction_repo = TransactionRepository(session)

            # Step 1: Mark as PROCESSING
            await receipt_repo.update(
                receipt_id=receipt_id,
                status=ReceiptStatus.PROCESSING,
            )
            await session.commit()

            # Step 2: Validate image quality
            t0 = time.monotonic()
            image_validator = ImageValidator()
            image_validator.raise_if_invalid(file_content, content_type)
            logger.info(f"⏱ bg_image_validation: {time.monotonic() - t0:.3f}s")

            # Step 3: Extract via Mistral Document AI
            t0 = time.monotonic()
            mistral_service = MistralDocumentService()
            extraction_result = await mistral_service.extract_receipt(
                file_content, content_type
            )
            logger.info(
                f"⏱ bg_mistral_extraction: {time.monotonic() - t0:.3f}s - "
                f"vendor={extraction_result.vendor_name}, "
                f"items={len(extraction_result.line_items)}"
            )

            # Step 3.5: Validate store is supported
            canonical_store = resolve_store_name(extraction_result.vendor_name)
            if canonical_store is None:
                raise UnsupportedStoreError(
                    f"Unsupported store: {extraction_result.vendor_name}",
                    details={"vendor_name": extraction_result.vendor_name},
                )
            cleaned_store_name = canonical_store

            # Step 4: Create transactions (batch insert — single flush)
            t0 = time.monotonic()
            final_date = receipt_date_override or extraction_result.receipt_date
            txn_date = final_date or date.today()

            transactions = [
                Transaction(
                    user_id=user_id,
                    receipt_id=receipt_id,
                    store_name=cleaned_store_name,
                    item_name=item.normalized_name,
                    item_price=item.total_price,
                    quantity=item.quantity,
                    unit_price=item.unit_price,
                    category=item.parent_category,
                    date=txn_date,
                    health_score=item.health_score,
                    original_description=item.original_description,
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
                    dp_packaging_type=item.dp_packaging_type,
                    dp_product_variant=item.dp_product_variant,
                    dp_article_code=item.dp_article_code,
                    dp_is_bio=item.dp_is_bio,
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

            # Step 6: Update receipt to COMPLETED
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

            logger.info(
                f"Background processing completed: receipt_id={receipt_id}, "
                f"store={cleaned_store_name}, items={len(extraction_result.line_items)}"
            )

            # Step 7: Rebuild enriched profile
            try:
                await EnrichedProfileService.rebuild_profile(user_id, session)
                await session.commit()
            except Exception as profile_err:
                logger.warning(
                    f"Failed to rebuild enriched profile after receipt {receipt_id}: "
                    f"{profile_err}"
                )
                await session.rollback()

        except UnsupportedStoreError as e:
            logger.warning(
                f"Unsupported store for receipt {receipt_id}: {e.message}"
            )
            await session.rollback()
            try:
                await receipt_repo.update(
                    receipt_id=receipt_id,
                    status=ReceiptStatus.FAILED,
                    error_code="unsupported_store",
                    error_message=e.message,
                )
                await session.commit()
            except Exception as update_err:
                logger.error(
                    f"Failed to update receipt status to FAILED: "
                    f"receipt_id={receipt_id}, error={update_err}"
                )
                await session.rollback()

        except Exception as e:
            logger.error(
                f"Background processing failed: receipt_id={receipt_id}, "
                f"error={e}",
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
