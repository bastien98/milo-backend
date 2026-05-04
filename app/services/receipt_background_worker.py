"""Background worker for async receipt processing.

Runs outside the request lifecycle with its own DB session.
Called via FastAPI BackgroundTasks from the upload endpoint.
"""

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
    mime_type: str = "application/pdf",
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

            # Step 2: Extract via Gemini Vision
            t0 = time.monotonic()
            gemini_service = GeminiVisionService()
            extraction_result = await gemini_service.extract_receipt(file_content, user_id=user_id, mime_type=mime_type)
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

            # Step 3.5: Post-extraction fraud checks
            from app.services.fraud import FraudDetectionService
            from app.config import get_settings

            bg_settings = get_settings()
            if bg_settings.FRAUD_DETECTION_ENABLED:
                t0 = time.monotonic()
                fraud_service = FraudDetectionService()

                item_count = len(extraction_result.line_items)
                preliminary_total = extraction_result.total or sum(
                    item.total_price for item in extraction_result.line_items
                )

                extraction_data = {
                    "store_name": cleaned_store_name,
                    "receipt_date": extraction_result.receipt_date,
                    "total_amount": preliminary_total,
                    "item_count": item_count,
                    "receipt_time": extraction_result.receipt_time,
                }

                # result_store collects computed values (e.g. fingerprint) from checks
                result_store: dict = {}
                fraud_result = await fraud_service.run_post_extraction_checks(
                    extraction_data,
                    user_id=user_id,
                    receipt_id=receipt_id,
                    receipt_repo=receipt_repo,
                    result_store=result_store,
                )

                if fraud_result.should_block:
                    blocking = fraud_result.blocking_signal
                    # Map check names to user-facing error codes and messages
                    error_code_map = {
                        "fingerprint": "duplicate_content",
                    }
                    error_message_map = {
                        "fingerprint": "This receipt appears to be a duplicate of one you already uploaded.",
                    }
                    check_name = blocking.check_name if blocking else ""
                    error_code = error_code_map.get(check_name, "fraud_detected")
                    error_message = error_message_map.get(check_name, "Receipt rejected by fraud detection.")

                    logger.warning(
                        f"Fraud check blocked receipt: receipt_id={receipt_id}, "
                        f"error_code={error_code}, flags={fraud_result.fraud_flags}"
                    )
                    await receipt_repo.update(
                        receipt_id=receipt_id,
                        status=ReceiptStatus.FAILED,
                        error_message=error_message,
                        error_code=error_code,
                        receipt_date=extraction_result.receipt_date,
                        store_name=cleaned_store_name,
                        fraud_score=fraud_result.fraud_score,
                        fraud_flags=fraud_result.fraud_flags_json,
                        receipt_fingerprint=result_store.get("receipt_fingerprint"),
                    )
                    await session.commit()
                    logger.info(f"bg_fraud_check: {time.monotonic() - t0:.3f}s — BLOCKED")
                    return

                # Store fraud metadata + fingerprint on the receipt
                await receipt_repo.update(
                    receipt_id=receipt_id,
                    fraud_score=fraud_result.fraud_score,
                    fraud_flags=fraud_result.fraud_flags_json,
                    receipt_fingerprint=result_store.get("receipt_fingerprint"),
                )
                logger.info(f"bg_fraud_check: {time.monotonic() - t0:.3f}s — CLEAN")

            # Step 4: Create transactions (batch insert — single flush)
            t0 = time.monotonic()
            final_date = extraction_result.receipt_date
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
                    is_deposit_refund=item.is_deposit_refund,
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
                    dp_article_codes=item.dp_article_codes,
                    dp_is_bio=item.dp_is_bio,
                    dp_packaging_type=item.dp_packaging_type,
                    dp_product_name_no_brand=item.dp_product_name_no_brand,
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
                store_branch=extraction_result.store_branch,
            )
            await session.commit()
            logger.info(f"⏱ bg_mark_completed: {time.monotonic() - t0:.3f}s")

            # Step 7: Check brand cashback deals (the only earning path — non-fatal).
            try:
                t0 = time.monotonic()
                from app.services.brand_cashback_service import (
                    BrandCashbackService,
                    ReceiptLineItemForMatching,
                )
                brand_cb_svc = BrandCashbackService(session)
                receipt_items_for_matching = [
                    ReceiptLineItemForMatching(
                        text=item.item_name,
                        codes=tuple(item.dp_article_codes),
                    )
                    for item in extraction_result.line_items
                ]
                await brand_cb_svc.check_receipt_for_brand_cashback(
                    receipt_id=receipt_id,
                    user_id=user_id,
                    receipt_line_items=receipt_items_for_matching,
                    store_name=cleaned_store_name,
                    receipt_date=extraction_result.receipt_date,
                )
                await session.commit()
                logger.info(f"⏱ bg_brand_cashback: {time.monotonic() - t0:.3f}s")
            except Exception as brand_cb_err:
                logger.warning(f"Brand cashback check failed (non-fatal): {brand_cb_err}")
                await session.rollback()

            # Step 8: Rebuild enriched profile (non-fatal)
            try:
                t0 = time.monotonic()
                from app.services.enriched_profile_service import EnrichedProfileService
                await EnrichedProfileService.rebuild_profile(user_id, session)
                await session.commit()
                logger.info(f"⏱ bg_enriched_profile_rebuild: {time.monotonic() - t0:.3f}s")
            except Exception as profile_err:
                logger.warning(f"Enriched profile rebuild failed (non-fatal): {profile_err}")
                await session.rollback()

            invalidate_user(user_id)

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
