from datetime import date, datetime
from typing import Optional

from fastapi import UploadFile

from app.models.enums import ReceiptStatus
from app.schemas.receipt import ReceiptUploadResponse, ExtractedItem
from app.services.image_validator import ImageValidator
from app.services.veryfi_service import VeryfiService
from app.services.categorization_service_gemini import CategorizationServiceGemini
from app.db.repositories.receipt_repo import ReceiptRepository
from app.db.repositories.transaction_repo import TransactionRepository


class ReceiptProcessorV2:
    """
    Receipt processing pipeline using Veryfi for OCR and Gemini for categorization.

    This v2 processor separates concerns:
    - Veryfi: Handles OCR extraction (item names, prices, quantities)
    - Gemini: Handles categorization and health scoring (replacing Claude)
    """

    def __init__(
        self,
        receipt_repo: ReceiptRepository,
        transaction_repo: TransactionRepository,
    ):
        self.image_validator = ImageValidator()
        self.veryfi_service = VeryfiService()
        self.categorization_service = CategorizationServiceGemini()
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
        4. Call Veryfi API for OCR extraction
        5. Call Gemini API for categorization and health scoring
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

            # Step 4: Extract data via Veryfi OCR
            veryfi_result = await self.veryfi_service.extract_receipt_data(
                file_content, filename
            )

            # Step 4b: Check for duplicate - if duplicate, don't save to database
            if veryfi_result.is_duplicate:
                # Delete the receipt record we created
                await self.receipt_repo.delete(receipt.id)

                # Veryfi only provides boolean duplicate flag, no similarity score
                warning_msg = "Duplicate receipt detected - not saved"

                # Return response with duplicate flag but no saved data
                return ReceiptUploadResponse(
                    receipt_id="",
                    status=ReceiptStatus.COMPLETED,
                    store_name=veryfi_result.vendor_name,
                    receipt_date=veryfi_result.date,
                    total_amount=veryfi_result.total,
                    items_count=0,
                    transactions=[],
                    warnings=[warning_msg],
                    is_duplicate=True,
                    duplicate_score=veryfi_result.duplicate_score,
                )

            # Step 5: Categorize items and clean data via Gemini
            categorization_result = await self.categorization_service.categorize_items(
                veryfi_result.line_items,
                vendor_name=veryfi_result.vendor_name,
            )

            # Use cleaned store name from Gemini (always lowercase for consistency)
            cleaned_store_name = (categorization_result.store_name or "Unknown").lower()

            # Use override date if provided, otherwise use Veryfi's extracted date
            final_date = receipt_date_override or veryfi_result.date

            # Step 6: Create transactions (only for non-duplicate receipts)
            transactions = []
            for item in categorization_result.items:
                transaction = await self.transaction_repo.create(
                    user_id=user_id,
                    receipt_id=receipt.id,
                    store_name=cleaned_store_name,
                    item_name=item.item_name,
                    item_price=item.item_price,
                    quantity=item.quantity,
                    unit_price=item.unit_price,
                    category=item.category,
                    date=final_date or date.today(),
                    health_score=item.health_score,
                )
                transactions.append(
                    ExtractedItem(
                        item_name=item.item_name,
                        item_price=item.item_price,
                        quantity=item.quantity,
                        unit_price=item.unit_price,
                        category=item.category,
                        health_score=item.health_score,
                    )
                )

            # Use Veryfi's total if available, otherwise calculate from items
            if veryfi_result.total and veryfi_result.total > 0:
                final_total = veryfi_result.total
            else:
                final_total = sum(item.item_price for item in categorization_result.items)

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
                is_duplicate=veryfi_result.is_duplicate,
                duplicate_score=veryfi_result.duplicate_score,
            )

        except Exception as e:
            # Update receipt with error status
            await self.receipt_repo.update(
                receipt_id=receipt.id,
                status=ReceiptStatus.FAILED,
                error_message=str(e),
            )
            raise

    def _get_file_type(self, content_type: str) -> str:
        """Get file type from content type."""
        mapping = {
            "image/jpeg": "jpg",
            "image/jpg": "jpg",
            "image/png": "png",
            "application/pdf": "pdf",
        }
        return mapping.get(content_type, "unknown")
