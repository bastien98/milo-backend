from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.core.exceptions import (
    ReceiptProcessingError,
    ImageValidationError,
    VeryfiAPIError,
    GeminiAPIError,
    ResourceNotFoundError,
    PermissionDeniedError,
    RateLimitExceededError,
)
from app.api.v2.router import api_router as api_router_v2
from app.db.session import init_db

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await init_db()
    yield
    # Shutdown
    pass


app = FastAPI(
    title=settings.APP_NAME,
    version="2.0.0",
    description="""
## Scandalicious API

Receipt scanning and expense tracking API powered by Veryfi OCR and AI.

### Features
- **Receipt Upload**: Scan receipts using Veryfi OCR with AI categorization & health scoring
- **Duplicate Detection**: Automatically detects and rejects duplicate receipts - not saved to database
- **Transaction Management**: View, edit, and delete transactions
- **Analytics**: Spending summaries, category breakdowns, and trends
- **AI Chat**: Ask questions about your spending with Dobby AI assistant

### Authentication
All endpoints require Firebase Authentication. Include the ID token in the Authorization header:
```
Authorization: Bearer <firebase_id_token>
```

### Rate Limits
- **Chat messages**: 100 per 30-day period
- **Receipt uploads**: 15 per 30-day period
""",
    lifespan=lifespan,
    openapi_tags=[
        {"name": "v2 - receipts", "description": "📄 Upload and manage receipts (Gemini AI)"},
        {"name": "v2 - chat", "description": "💬 AI-powered spending assistant (Gemini AI)"},
        {"name": "v2 - transactions", "description": "💳 View and manage transactions"},
        {"name": "v2 - analytics", "description": "📊 Spending analytics and insights"},
        {"name": "v2 - rate-limit", "description": "⏱️ Rate limit status"},
        {"name": "v2 - profile", "description": "👤 User profile management"},
        {"name": "v2 - health", "description": "🏥 Health checks"},
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


@app.exception_handler(VeryfiAPIError)
async def veryfi_api_exception_handler(request: Request, exc: VeryfiAPIError):
    error_type = exc.details.get("error_type", "unknown")

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


@app.exception_handler(GeminiAPIError)
async def gemini_api_exception_handler(request: Request, exc: GeminiAPIError):
    error_type = exc.details.get("error_type", "unknown")

    content = {
        "error": "llm_service_error",
        "message": "AI service temporarily unavailable",
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
    return JSONResponse(
        status_code=500,
        content={
            "error": "internal_error",
            "message": "An unexpected error occurred",
        },
    )


# Include API router
app.include_router(api_router_v2, prefix="/api/v2")


# Root health check
@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": settings.APP_NAME}
