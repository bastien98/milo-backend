from datetime import date, datetime
from typing import List, Optional
import io

from PIL import Image
from fastapi import UploadFile

from app.core.exceptions import ReceiptProcessingError
from app.models.enums import ReceiptStatus
from app.schemas.receipt import ReceiptUploadResponse, ExtractedItem
from app.services.image_validator import ImageValidator
from app.services.pdf_service import PDFService
from app.services.claude_service import ClaudeService
from app.db.repositories.receipt_repo import ReceiptRepository
from app.db.repositories.transaction_repo import TransactionRepository


class ReceiptProcessor:
    """Orchestrates the receipt processing pipeline."""

    def __init__(
        self,
        receipt_repo: ReceiptRepository,
        transaction_repo: TransactionRepository,
    ):
        self.image_validator = ImageValidator()
        self.pdf_service = PDFService()
        self.claude_service = ClaudeService()
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
        4. Convert PDF to images if needed
        5. Call Claude Vision API
        6. Parse and validate response
        7. Create transaction records
        8. Update receipt record (status: completed)
        9. Return results
        """
        warnings = []

        # Step 1: Basic validation
        content_type = file.content_type or "application/octet-stream"
        self.image_validator.validate_content_type(content_type)

        file_content = await file.read()
        file_type = self._get_file_type(content_type)

        # Step 2: Create receipt record
        receipt = await self.receipt_repo.create(
            user_id=user_id,
            filename=file.filename or "receipt",
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

            # Step 4: Prepare image(s) for Claude
            images = await self._prepare_images(file_content, content_type)

            # Step 5-6: Extract data via Claude
            extraction_result = await self.claude_service.extract_receipt_data(images)

            # Use override date if provided
            final_date = receipt_date_override or extraction_result.receipt_date

            # Step 7: Create transactions
            transactions = []
            for item in extraction_result.items:
                transaction = await self.transaction_repo.create(
                    user_id=user_id,
                    receipt_id=receipt.id,
                    store_name=extraction_result.store_name,
                    item_name=item.item_name,
                    item_price=item.item_price,
                    quantity=item.quantity,
                    unit_price=item.unit_price,
                    category=item.category,
                    date=final_date or date.today(),
                )
                transactions.append(
                    ExtractedItem(
                        item_name=item.item_name,
                        item_price=item.item_price,
                        quantity=item.quantity,
                        unit_price=item.unit_price,
                        category=item.category,
                    )
                )

            # Step 8: Update receipt
            await self.receipt_repo.update(
                receipt_id=receipt.id,
                status=ReceiptStatus.COMPLETED,
                store_name=extraction_result.store_name,
                receipt_date=final_date,
                total_amount=extraction_result.total_amount,
                processed_at=datetime.utcnow(),
            )

            # Step 9: Return results
            return ReceiptUploadResponse(
                receipt_id=receipt.id,
                status=ReceiptStatus.COMPLETED,
                store_name=extraction_result.store_name,
                receipt_date=final_date,
                total_amount=extraction_result.total_amount,
                items_count=len(transactions),
                transactions=transactions,
                warnings=warnings,
            )

        except Exception as e:
            # Update receipt with error status
            await self.receipt_repo.update(
                receipt_id=receipt.id,
                status=ReceiptStatus.FAILED,
                error_message=str(e),
            )
            raise

    async def _prepare_images(
        self, file_content: bytes, content_type: str
    ) -> List[bytes]:
        """Convert file to images for Claude."""
        if self.pdf_service.is_pdf(content_type):
            return await self.pdf_service.convert_to_images(file_content)
        else:
            # Convert image to PNG for consistency
            image = Image.open(io.BytesIO(file_content))
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            return [buffer.getvalue()]

    def _get_file_type(self, content_type: str) -> str:
        """Get file type from content type."""
        mapping = {
            "image/jpeg": "jpg",
            "image/jpg": "jpg",
            "image/png": "png",
            "application/pdf": "pdf",
        }
        return mapping.get(content_type, "unknown")
