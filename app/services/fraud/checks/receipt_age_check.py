"""Receipt age validation — 7-day rolling window."""

from datetime import date, timedelta
from typing import Any

from app.services.fraud.base import BaseFraudCheck
from app.services.fraud.models import FraudSignal

RECEIPT_MAX_AGE_DAYS = 7


class ReceiptAgeCheck(BaseFraudCheck):
    """Rejects receipts older than 7 days.

    Runs post-extraction since we need the Gemini-extracted receipt_date.
    Controlled by FRAUD_DETECTION_ENABLED at the callsite.
    """

    name = "receipt_age"

    async def check_post_extraction(
        self, extraction_data: dict[str, Any], **ctx: Any
    ) -> list[FraudSignal]:
        receipt_date: date | None = extraction_data.get("receipt_date")

        if receipt_date is None:
            return [
                FraudSignal(
                    check_name=self.name,
                    flag="receipt_date_missing",
                    score=1.0,
                    blocking=True,
                )
            ]

        today = date.today()
        cutoff = today - timedelta(days=RECEIPT_MAX_AGE_DAYS)

        if receipt_date < cutoff:
            return [
                FraudSignal(
                    check_name=self.name,
                    flag=f"receipt_too_old:date={receipt_date.isoformat()},cutoff={cutoff.isoformat()}",
                    score=1.0,
                    blocking=True,
                )
            ]

        return []
