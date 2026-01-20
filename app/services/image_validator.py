import io
from dataclasses import dataclass
from typing import List

from PIL import Image

from app.core.exceptions import ImageValidationError


@dataclass
class ValidationResult:
    is_valid: bool
    errors: List[str]
    warnings: List[str]


class ImageValidator:
    """Validates image quality before LLM processing."""

    MIN_WIDTH = 300
    MIN_HEIGHT = 400
    MAX_FILE_SIZE_MB = 20
    SUPPORTED_IMAGE_FORMATS = {"JPEG", "PNG"}
    SUPPORTED_CONTENT_TYPES = {
        "image/jpeg",
        "image/jpg",
        "image/png",
        "application/pdf",
    }

    def validate_content_type(self, content_type: str) -> None:
        """Validate that the content type is supported."""
        if content_type not in self.SUPPORTED_CONTENT_TYPES:
            raise ImageValidationError(
                f"Unsupported file type: {content_type}",
                details={"supported_types": list(self.SUPPORTED_CONTENT_TYPES)},
            )

    def validate(self, file_content: bytes, content_type: str) -> ValidationResult:
        """
        Validate image quality for receipt processing.

        Checks:
        1. File size within limits
        2. Valid image format
        3. Minimum resolution
        4. Image is not corrupted
        """
        errors = []
        warnings = []

        # File size check
        size_mb = len(file_content) / (1024 * 1024)
        if size_mb > self.MAX_FILE_SIZE_MB:
            errors.append(
                f"File size {size_mb:.1f}MB exceeds maximum {self.MAX_FILE_SIZE_MB}MB"
            )

        # Skip image checks for PDF (handled separately)
        if content_type == "application/pdf":
            return ValidationResult(
                is_valid=len(errors) == 0, errors=errors, warnings=warnings
            )

        try:
            image = Image.open(io.BytesIO(file_content))

            # Format check
            if image.format not in self.SUPPORTED_IMAGE_FORMATS:
                errors.append(f"Unsupported image format: {image.format}")

            # Resolution check
            width, height = image.size
            if width < self.MIN_WIDTH or height < self.MIN_HEIGHT:
                errors.append(
                    f"Image resolution {width}x{height} is below minimum "
                    f"{self.MIN_WIDTH}x{self.MIN_HEIGHT}"
                )

            # Basic quality warning
            if width < 600 or height < 800:
                warnings.append("Low resolution image may affect extraction accuracy")

        except Exception as e:
            errors.append(f"Invalid or corrupted image: {str(e)}")

        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )

    def raise_if_invalid(self, file_content: bytes, content_type: str) -> List[str]:
        """Validate and raise exception if invalid. Returns warnings."""
        result = self.validate(file_content, content_type)
        if not result.is_valid:
            raise ImageValidationError(
                "Image validation failed",
                details={"errors": result.errors},
            )
        return result.warnings
