import hashlib
from datetime import date, datetime
from typing import Optional

from fastapi import UploadFile

from app.models.enums import ReceiptStatus
from app.schemas.receipt import ReceiptUploadResponse, ExtractedItem
from app.services.image_validator import ImageValidator
from app.services.gemini_vision_service import GeminiVisionService
from app.db.repositories.receipt_repo import ReceiptRepository
from app.db.repositories.transaction_repo import TransactionRepository


class ReceiptProcessorV2:
    """
    Receipt processing pipeline using Gemini Vision for OCR and extraction.

    This v2 processor uses a single Gemini call that handles:
    - OCR extraction (item names, prices, quantities)
    - Semantic normalization (cleaned product names for search)
    - Granular categorization (~200 categories)
    - Health scoring
    - Belgian pricing conventions (comma→dot, Hoeveelheidsvoordeel)
    - Deposit detection (Leeggoed/Vidange)
    """

    def __init__(
        self,
        receipt_repo: ReceiptRepository,
        transaction_repo: TransactionRepository,
    ):
        self.image_validator = ImageValidator()
        self.gemini_vision_service = GeminiVisionService()
        self.receipt_repo = receipt_repo
        self.transaction_repo = transaction_repo

    async def process_receipt(
        self,
        user_id: str,
        file: UploadFile,
        receipt_date_override: Optional[date] = None,
    ) -> ReceiptUploadResponse:
        """
        Main processing pipeline - synchronous from iOS app perspective.

        Steps:
        1. Validate file type and size
        2. Create receipt record (status: processing)
        3. Validate image quality
        4. Check for duplicate receipt (content hash)
        5. Call Gemini Vision for OCR + normalization + categorization
        6. Create transaction records
        7. Update receipt record (status: completed)
        8. Return results
        """
        warnings = []

        # Step 1: Basic validation
        content_type = file.content_type or "application/octet-stream"
        self.image_validator.validate_content_type(content_type)

        file_content = await file.read()
        file_type = self._get_file_type(content_type)
        filename = file.filename or "receipt"

        # Step 2: Create receipt record
        receipt = await self.receipt_repo.create(
            user_id=user_id,
            filename=filename,
            file_type=file_type,
            file_size=len(file_content),
            status=ReceiptStatus.PROCESSING,
        )

        try:
            # Step 3: Validate image quality
            validation_warnings = self.image_validator.raise_if_invalid(
                file_content, content_type
            )
            warnings.extend(validation_warnings)

            # Step 4: Check for duplicate (simple content hash)
            content_hash = self._compute_content_hash(file_content)
            is_duplicate = await self._check_duplicate_hash(user_id, content_hash)

            if is_duplicate:
                # Delete the receipt record we created
                await self.receipt_repo.delete(receipt.id)

                warning_msg = "Duplicate receipt detected - not saved"

                return ReceiptUploadResponse(
                    receipt_id="",
                    status=ReceiptStatus.COMPLETED,
                    store_name=None,
                    receipt_date=None,
                    total_amount=None,
                    items_count=0,
                    transactions=[],
                    warnings=[warning_msg],
                    is_duplicate=True,
                    duplicate_score=1.0,
                )

            # Step 5: Extract + normalize + categorize via Gemini Vision (single call)
            extraction_result = await self.gemini_vision_service.extract_receipt(
                file_content, content_type
            )

            # Use cleaned store name (always lowercase for consistency)
            cleaned_store_name = (extraction_result.vendor_name or "Unknown").lower()

            # Use override date if provided, otherwise use extracted date
            final_date = receipt_date_override or extraction_result.receipt_date

            # Step 6: Create transactions with new fields
            transactions = []
            for item in extraction_result.line_items:
                transaction = await self.transaction_repo.create(
                    user_id=user_id,
                    receipt_id=receipt.id,
                    store_name=cleaned_store_name,
                    item_name=item.normalized_name,  # Use normalized name as item_name
                    item_price=item.total_price,
                    quantity=item.quantity,
                    unit_price=item.unit_price,
                    category=item.parent_category,  # Broad category
                    date=final_date or date.today(),
                    health_score=item.health_score,
                    # New fields
                    original_description=item.original_description,
                    normalized_name=item.normalized_name,
                    is_deposit=item.is_deposit,
                    granular_category=item.granular_category,
                )
                transactions.append(
                    ExtractedItem(
                        item_id=transaction.id,
                        item_name=item.normalized_name,
                        item_price=item.total_price,
                        quantity=item.quantity,
                        unit_price=item.unit_price,
                        category=item.parent_category,
                        health_score=item.health_score,
                        # New fields in response
                        original_description=item.original_description,
                        normalized_name=item.normalized_name,
                        is_deposit=item.is_deposit,
                        granular_category=item.granular_category,
                    )
                )

            # Use extracted total if available, otherwise calculate from items
            if extraction_result.total and extraction_result.total > 0:
                final_total = extraction_result.total
            else:
                final_total = sum(item.total_price for item in extraction_result.line_items)

            # Step 7: Update receipt
            await self.receipt_repo.update(
                receipt_id=receipt.id,
                status=ReceiptStatus.COMPLETED,
                store_name=cleaned_store_name,
                receipt_date=final_date,
                total_amount=final_total,
                processed_at=datetime.utcnow(),
            )

            # Step 8: Return results
            return ReceiptUploadResponse(
                receipt_id=receipt.id,
                status=ReceiptStatus.COMPLETED,
                store_name=cleaned_store_name,
                receipt_date=final_date,
                total_amount=final_total,
                items_count=len(transactions),
                transactions=transactions,
                warnings=warnings,
                is_duplicate=False,
                duplicate_score=None,
            )

        except Exception as e:
            # Update receipt with error status
            await self.receipt_repo.update(
                receipt_id=receipt.id,
                status=ReceiptStatus.FAILED,
                error_message=str(e),
            )
            raise

    def _compute_content_hash(self, content: bytes) -> str:
        """Compute SHA-256 hash of file content for duplicate detection."""
        return hashlib.sha256(content).hexdigest()

    async def _check_duplicate_hash(self, user_id: str, content_hash: str) -> bool:
        """Check if a receipt with the same content hash already exists.

        Note: This is a simple implementation. For production, you may want to
        store the hash in the receipts table and query it directly.
        """
        # For now, we don't persist the hash. This means we can't detect
        # duplicates across sessions. A more robust implementation would
        # add a content_hash column to the receipts table.
        # TODO: Add content_hash column to receipts table for persistent duplicate detection
        return False

    def _get_file_type(self, content_type: str) -> str:
        """Get file type from content type."""
        mapping = {
            "image/jpeg": "jpg",
            "image/jpg": "jpg",
            "image/png": "png",
            "application/pdf": "pdf",
        }
        return mapping.get(content_type, "unknown")
