import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.core.exceptions import (
    ReceiptProcessingError,
    ImageValidationError,
    ClaudeAPIError,
    VeryfiAPIError,
    ResourceNotFoundError,
    PermissionDeniedError,
    RateLimitExceededError,
)
from app.api.v1.router import api_router
from app.db.session import init_db

settings = get_settings()

# Configure logging - suppress noisy third-party loggers
logging.basicConfig(level=logging.DEBUG if settings.DEBUG else logging.INFO)
logger = logging.getLogger(__name__)

# Silence noisy third-party libraries
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("cachecontrol").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("google").setLevel(logging.WARNING)
logging.getLogger("firebase_admin").setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting Scandalicious Backend...")
    await init_db()
    yield
    # Shutdown
    logger.info("Shutting down Scandalicious Backend...")


app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    description="""
## Scandelicious API

Receipt scanning and expense tracking API powered by Veryfi OCR and Claude AI.

### Features
- **Receipt Upload**: Scan receipts using Veryfi OCR with Claude AI categorization
- **Transaction Management**: View, edit, and delete transactions
- **Analytics**: Spending summaries, category breakdowns, and trends
- **AI Chat**: Ask questions about your spending with Dobby AI assistant

### Authentication
All endpoints require Firebase Authentication. Include the ID token in the Authorization header:
```
Authorization: Bearer <firebase_id_token>
```
""",
    lifespan=lifespan,
    openapi_tags=[
        {"name": "receipts", "description": "Upload and manage receipts"},
        {"name": "transactions", "description": "View and manage transactions"},
        {"name": "analytics", "description": "Spending analytics and insights"},
        {"name": "chat", "description": "AI-powered spending assistant"},
        {"name": "rate-limit", "description": "Rate limit status"},
        {"name": "profile", "description": "User profile management"},
        {"name": "health", "description": "Health checks"},
    ],
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Exception handlers
@app.exception_handler(ImageValidationError)
async def image_validation_exception_handler(
    request: Request, exc: ImageValidationError
):
    return JSONResponse(
        status_code=400,
        content={
            "error": "image_validation_error",
            "message": exc.message,
            "details": exc.details,
        },
    )


@app.exception_handler(ReceiptProcessingError)
async def receipt_processing_exception_handler(
    request: Request, exc: ReceiptProcessingError
):
    return JSONResponse(
        status_code=422,
        content={
            "error": "receipt_processing_error",
            "message": exc.message,
            "details": exc.details,
        },
    )


@app.exception_handler(ClaudeAPIError)
async def claude_api_exception_handler(request: Request, exc: ClaudeAPIError):
    error_type = exc.details.get("error_type", "unknown")
    logger.error(f"ClaudeAPIError: {exc.message} (type={error_type}, details={exc.details})")

    content = {
        "error": "llm_service_error",
        "message": "Receipt extraction service temporarily unavailable",
        "details": {"retry_after": 30},
    }

    # Include detailed error info in debug mode
    if settings.DEBUG:
        content["debug"] = {
            "error_type": error_type,
            "message": exc.message,
            "details": exc.details,
        }

    return JSONResponse(status_code=503, content=content)


@app.exception_handler(VeryfiAPIError)
async def veryfi_api_exception_handler(request: Request, exc: VeryfiAPIError):
    error_type = exc.details.get("error_type", "unknown")
    logger.error(f"VeryfiAPIError: {exc.message} (type={error_type}, details={exc.details})")

    content = {
        "error": "ocr_service_error",
        "message": "Receipt OCR service temporarily unavailable",
        "details": {"retry_after": 30},
    }

    # Include detailed error info in debug mode
    if settings.DEBUG:
        content["debug"] = {
            "error_type": error_type,
            "message": exc.message,
            "details": exc.details,
        }

    return JSONResponse(status_code=503, content=content)


@app.exception_handler(ResourceNotFoundError)
async def not_found_exception_handler(request: Request, exc: ResourceNotFoundError):
    return JSONResponse(
        status_code=404,
        content={
            "error": "not_found",
            "message": exc.message,
        },
    )


@app.exception_handler(PermissionDeniedError)
async def permission_denied_exception_handler(
    request: Request, exc: PermissionDeniedError
):
    return JSONResponse(
        status_code=403,
        content={
            "error": "permission_denied",
            "message": exc.message,
        },
    )


@app.exception_handler(RateLimitExceededError)
async def rate_limit_exceeded_exception_handler(
    request: Request, exc: RateLimitExceededError
):
    """Handle rate limit exceeded errors with 429 status."""
    retry_after = exc.details.get("retry_after_seconds", 86400)

    return JSONResponse(
        status_code=429,
        content={
            "error": "rate_limit_exceeded",
            "message": exc.message,
            "messages_used": exc.details.get("messages_used"),
            "messages_limit": exc.details.get("messages_limit"),
            "period_end_date": exc.details.get("period_end_date"),
            "retry_after_seconds": retry_after,
        },
        headers={
            "Retry-After": str(retry_after),
        },
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Handle FastAPI HTTPExceptions with consistent format."""
    error_type = {
        400: "bad_request",
        401: "unauthorized",
        403: "forbidden",
        404: "not_found",
        422: "validation_error",
    }.get(exc.status_code, "http_error")

    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": error_type,
            "message": exc.detail if isinstance(exc.detail, str) else str(exc.detail),
        },
        headers=exc.headers,
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    logger.exception("Unexpected error occurred")
    return JSONResponse(
        status_code=500,
        content={
            "error": "internal_error",
            "message": "An unexpected error occurred",
        },
    )


# Include API routers
app.include_router(api_router, prefix=settings.API_V1_PREFIX)


# Root health check
@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": settings.APP_NAME}
