from typing import Optional, Dict, Any


class ScandaliciousException(Exception):
    """Base exception for Scandalicious backend."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        self.message = message
        self.details = details or {}
        super().__init__(message)


class ReceiptProcessingError(ScandaliciousException):
    """Raised when receipt processing fails."""

    pass


class ImageValidationError(ScandaliciousException):
    """Raised when image validation fails."""

    pass


class ClaudeAPIError(ScandaliciousException):
    """Raised when Claude API call fails."""

    pass


class ResourceNotFoundError(ScandaliciousException):
    """Raised when a requested resource is not found."""

    pass


class PermissionDeniedError(ScandaliciousException):
    """Raised when user doesn't have permission for an action."""

    pass
