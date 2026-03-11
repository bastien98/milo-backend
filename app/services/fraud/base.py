"""Abstract base class for fraud checks."""

from abc import ABC, abstractmethod
from typing import Any

from app.services.fraud.models import FraudSignal


class BaseFraudCheck(ABC):
    """Base class for all fraud checks.

    To add a new check:
    1. Create a new file in checks/
    2. Subclass BaseFraudCheck
    3. Implement check_upload and/or check_post_extraction
    4. Register in FraudDetectionService.__init__
    """

    name: str = "unnamed_check"

    async def check_upload(
        self, file_content: bytes, **ctx: Any
    ) -> list[FraudSignal]:
        """Run at upload time. Override to add upload-time checks.

        Return a list of FraudSignal objects, or empty list if clean.
        """
        return []

    async def check_post_extraction(
        self, extraction_data: dict[str, Any], **ctx: Any
    ) -> list[FraudSignal]:
        """Run after Gemini extraction in background. Override to add post-extraction checks.

        extraction_data contains: store_name, receipt_date, total_amount, item_count.
        ctx may contain: user_id, receipt_id, db_session.

        Return a list of FraudSignal objects, or empty list if clean.
        """
        return []
