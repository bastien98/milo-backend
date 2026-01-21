import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.core.exceptions import (
    ScandaliciousException,
    ReceiptProcessingError,
    ImageValidationError,
    ClaudeAPIError,
    ResourceNotFoundError,
    PermissionDeniedError,
)
from app.api.v1.router import api_router
from app.db.session import init_db

settings = get_settings()

logging.basicConfig(level=logging.DEBUG if settings.DEBUG else logging.INFO)
logger = logging.getLogger(__name__)


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
    lifespan=lifespan,
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


# Include API router
app.include_router(api_router, prefix=settings.API_V1_PREFIX)


# Root health check
@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": settings.APP_NAME}
