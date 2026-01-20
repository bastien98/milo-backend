from typing import Optional, Dict, Any


class DobbyException(Exception):
    """Base exception for Dobby backend."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        self.message = message
        self.details = details or {}
        super().__init__(message)


class ReceiptProcessingError(DobbyException):
    """Raised when receipt processing fails."""

    pass


class ImageValidationError(DobbyException):
    """Raised when image validation fails."""

    pass


class ClaudeAPIError(DobbyException):
    """Raised when Claude API call fails."""

    pass


class ResourceNotFoundError(DobbyException):
    """Raised when a requested resource is not found."""

    pass


class PermissionDeniedError(DobbyException):
    """Raised when user doesn't have permission for an action."""

    pass
