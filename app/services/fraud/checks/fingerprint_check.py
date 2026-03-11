"""Near-duplicate detection via receipt fingerprinting."""

import hashlib
import logging
from datetime import date
from typing import Any, Optional

from app.services.fraud.base import BaseFraudCheck
from app.services.fraud.models import FraudSignal

logger = logging.getLogger(__name__)


class FingerprintCheck(BaseFraudCheck):
    """Catches near-duplicate receipts that bypass exact hash matching.

    Computes a fingerprint from extracted data (store + date + total + item_count)
    and checks if the same user already has a receipt with the same fingerprint.

    Runs post-extraction since we need Gemini-extracted fields.
    """

    name = "fingerprint"

    async def check_post_extraction(
        self, extraction_data: dict[str, Any], **ctx: Any
    ) -> list[FraudSignal]:
        store_name: str | None = extraction_data.get("store_name")
        receipt_date: date | None = extraction_data.get("receipt_date")
        total_amount: float | None = extraction_data.get("total_amount")
        item_count: int | None = extraction_data.get("item_count")
        receipt_time: str | None = extraction_data.get("receipt_time")

        # Can't compute fingerprint without all fields
        if not all([store_name, receipt_date, total_amount is not None, item_count is not None]):
            return []

        fingerprint = compute_receipt_fingerprint(
            store_name=store_name,  # type: ignore[arg-type]
            receipt_date=receipt_date,  # type: ignore[arg-type]
            total_amount=total_amount,  # type: ignore[arg-type]
            item_count=item_count,  # type: ignore[arg-type]
            receipt_time=receipt_time,
        )

        # Store fingerprint in context for the caller to persist
        ctx_store = ctx.get("result_store")
        if ctx_store is not None and isinstance(ctx_store, dict):
            ctx_store["receipt_fingerprint"] = fingerprint

        # DB lookup — requires receipt_repo and user_id in context
        receipt_repo = ctx.get("receipt_repo")
        user_id = ctx.get("user_id")
        receipt_id = ctx.get("receipt_id")

        if receipt_repo is None or user_id is None:
            logger.warning("FingerprintCheck: missing receipt_repo or user_id in context, skipping DB lookup")
            return []

        existing = await receipt_repo.find_by_fingerprint_and_user(
            fingerprint=fingerprint,
            user_id=user_id,
            exclude_receipt_id=receipt_id,
        )

        if existing:
            logger.warning(
                f"Near-duplicate receipt detected: receipt_id={receipt_id}, "
                f"matches={existing.id}, fingerprint={fingerprint}"
            )
            return [
                FraudSignal(
                    check_name=self.name,
                    flag=f"duplicate_content:matches={existing.id}",
                    score=1.0,
                    blocking=True,
                )
            ]

        return []


def compute_receipt_fingerprint(
    store_name: str,
    receipt_date: date,
    total_amount: float,
    item_count: int,
    receipt_time: Optional[str] = None,
) -> str:
    """Deterministic hash from extracted receipt data."""
    time_part = receipt_time if receipt_time else ""
    raw = f"{store_name.lower().strip()}|{receipt_date.isoformat()}|{time_part}|{total_amount:.2f}|{item_count}"
    return hashlib.sha256(raw.encode()).hexdigest()
