import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.core.exceptions import (
    DobbyException,
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
    logger.info("Starting Dobby Backend...")
    await init_db()
    yield
    # Shutdown
    logger.info("Shutting down Dobby Backend...")


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
    return JSONResponse(
        status_code=503,
        content={
            "error": "llm_service_error",
            "message": "Receipt extraction service temporarily unavailable",
            "details": {"retry_after": 30},
        },
    )


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
