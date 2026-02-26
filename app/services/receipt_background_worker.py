"""Background worker for async receipt processing.

Runs outside the request lifecycle with its own DB session.
Called via FastAPI BackgroundTasks from the upload endpoint.
"""

import time
from datetime import date, datetime, timezone
from datetime import time as dt_time
from typing import Optional

import structlog

from app.db.repositories.receipt_repo import ReceiptRepository
from app.db.repositories.transaction_repo import TransactionRepository
from app.db.session import async_session_maker
from app.models.enums import ReceiptStatus
from app.services.enriched_profile_service import EnrichedProfileService
from app.services.gemini_vision_service import GeminiVisionService
from app.services.image_validator import ImageValidator

logger = structlog.get_logger(__name__)


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
    log = logger.bind(receipt_id=receipt_id, user_id=user_id)
    log.info("receipt_uploaded", filename=filename, file_type=file_type, file_size_bytes=len(file_content))

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
            log.info("image_validated", duration_ms=round((time.monotonic() - t0) * 1000, 1))

            # Step 3: Extract via Gemini Vision
            t0 = time.monotonic()
            log.info("ocr_started", provider="gemini_vision")
            gemini_service = GeminiVisionService()
            extraction_result = await gemini_service.extract_receipt(
                file_content, content_type
            )
            ocr_duration_ms = round((time.monotonic() - t0) * 1000, 1)
            log.info(
                "ocr_completed",
                provider="gemini_vision",
                duration_ms=ocr_duration_ms,
                vendor_name=extraction_result.vendor_name,
                items_count=len(extraction_result.line_items),
            )

            # Step 4: Create transactions
            t0 = time.monotonic()
            cleaned_store_name = (extraction_result.vendor_name or "Unknown").lower()
            final_date = receipt_date_override or extraction_result.receipt_date

            for item in extraction_result.line_items:
                await transaction_repo.create(
                    user_id=user_id,
                    receipt_id=receipt_id,
                    store_name=cleaned_store_name,
                    item_name=item.normalized_name,
                    item_price=item.total_price,
                    quantity=item.quantity,
                    unit_price=item.unit_price,
                    category=item.parent_category,
                    date=final_date or date.today(),
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
                )
            log.info(
                "transactions_created",
                count=len(extraction_result.line_items),
                duration_ms=round((time.monotonic() - t0) * 1000, 1),
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

            log.info(
                "receipt_completed",
                store_name=cleaned_store_name,
                items_count=len(extraction_result.line_items),
                total_amount=final_total,
            )

            # Step 7: Rebuild enriched profile
            try:
                await EnrichedProfileService.rebuild_profile(user_id, session)
                await session.commit()
            except Exception as profile_err:
                log.warning("enriched_profile_rebuild_failed", error=str(profile_err))
                await session.rollback()

        except Exception as e:
            log.error("ocr_failed", error=str(e), exc_info=True)
            await session.rollback()
            try:
                await receipt_repo.update(
                    receipt_id=receipt_id,
                    status=ReceiptStatus.FAILED,
                    error_message=str(e),
                )
                await session.commit()
            except Exception as update_err:
                log.error("receipt_status_update_failed", error=str(update_err))
                await session.rollback()
