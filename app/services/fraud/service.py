"""Fraud detection orchestrator.

Runs all registered checks and aggregates their signals into a single result.
"""

import logging
from typing import Any

from app.services.fraud.base import BaseFraudCheck
from app.services.fraud.models import FraudCheckResult

logger = logging.getLogger(__name__)


class FraudDetectionService:
    """Orchestrates all registered fraud checks.

    To add a new check:
    1. Create a new class in checks/ that extends BaseFraudCheck
    2. Add it to the default checks list below
    """

    def __init__(self, checks: list[BaseFraudCheck] | None = None):
        if checks is not None:
            self.checks = checks
        else:
            from app.services.fraud.checks.pdf_metadata_check import PdfMetadataCheck
            from app.services.fraud.checks.jpeg_metadata_check import JpegMetadataCheck
            from app.services.fraud.checks.receipt_age_check import ReceiptAgeCheck
            from app.services.fraud.checks.fingerprint_check import FingerprintCheck

            self.checks = [
                PdfMetadataCheck(),
                JpegMetadataCheck(),
                ReceiptAgeCheck(),
                FingerprintCheck(),
            ]

    async def run_upload_checks(
        self, file_content: bytes, **ctx: Any
    ) -> FraudCheckResult:
        """Run all upload-time checks. Called from the upload endpoint."""
        signals = []
        checks_run = []
        for check in self.checks:
            try:
                result = await check.check_upload(file_content, **ctx)
                signals.extend(result)
                checks_run.append(check.name)
            except Exception as e:
                logger.error(f"Fraud check '{check.name}' failed during upload: {e}", exc_info=True)

        result = FraudCheckResult(signals=signals)
        logger.info(
            f"Upload fraud checks completed: checks_run={checks_run}, "
            f"score={result.fraud_score:.2f}, signals={len(signals)}, "
            f"flags={result.fraud_flags}, block={result.should_block}"
        )
        return result

    async def run_post_extraction_checks(
        self, extraction_data: dict[str, Any], **ctx: Any
    ) -> FraudCheckResult:
        """Run all post-extraction checks. Called from the background worker."""
        signals = []
        checks_run = []
        for check in self.checks:
            try:
                result = await check.check_post_extraction(extraction_data, **ctx)
                signals.extend(result)
                checks_run.append(check.name)
            except Exception as e:
                logger.error(f"Fraud check '{check.name}' failed post-extraction: {e}", exc_info=True)

        result = FraudCheckResult(signals=signals)
        logger.info(
            f"Post-extraction fraud checks completed: checks_run={checks_run}, "
            f"score={result.fraud_score:.2f}, signals={len(signals)}, "
            f"flags={result.fraud_flags}, block={result.should_block}"
        )
        return result
