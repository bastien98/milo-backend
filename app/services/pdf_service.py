import io
from typing import List

from app.core.exceptions import ReceiptProcessingError


class PDFService:
    """Converts PDF receipts to images for Claude Vision API."""

    DPI = 200  # Good balance between quality and size

    async def convert_to_images(self, pdf_content: bytes) -> List[bytes]:
        """
        Convert PDF pages to PNG images.

        For receipts, typically only first page is needed,
        but we handle multi-page for long receipts.
        """
        try:
            # Import here to handle missing poppler gracefully
            import pdf2image

            images = pdf2image.convert_from_bytes(
                pdf_content,
                dpi=self.DPI,
                fmt="PNG",
            )

            result = []
            for img in images:
                buffer = io.BytesIO()
                img.save(buffer, format="PNG", optimize=True)
                result.append(buffer.getvalue())

            return result

        except Exception as e:
            if "poppler" in str(e).lower():
                raise ReceiptProcessingError(
                    "PDF processing not available. Please upload an image instead.",
                    details={"error": "poppler not installed"},
                )
            raise ReceiptProcessingError(
                f"Failed to process PDF: {str(e)}",
                details={"error": str(e)},
            )

    def is_pdf(self, content_type: str) -> bool:
        """Check if the content type is PDF."""
        return content_type == "application/pdf"
