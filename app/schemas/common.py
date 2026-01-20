from typing import Optional, Dict, Any, List

from pydantic import BaseModel


class ErrorResponse(BaseModel):
    error: str
    message: str
    details: Optional[Dict[str, Any]] = None


class ValidationErrorDetail(BaseModel):
    field: str
    message: str


class ValidationErrorResponse(BaseModel):
    error: str = "validation_error"
    message: str = "Request validation failed"
    details: List[ValidationErrorDetail]


class PaginatedResponse(BaseModel):
    total: int
    page: int
    page_size: int
    total_pages: int
