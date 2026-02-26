"""Request logging middleware.

Logs every HTTP request with method, path, status_code, duration_ms,
user_id, and a unique request_id (UUID). Adds X-Request-ID response header.
Skips /health and /docs paths to reduce noise.
"""

import time
import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

logger = structlog.get_logger("request")

SKIP_PATHS = {"/health", "/docs", "/openapi.json", "/redoc"}


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.url.path in SKIP_PATHS:
            return await call_next(request)

        request_id = str(uuid.uuid4())
        start = time.monotonic()

        # Bind request context for downstream loggers
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        # Try to extract user_id from auth state (set by security dependency later)
        # We'll extract it from the Authorization header parse if possible,
        # but the actual user_id is only available after the endpoint runs.
        # We log it post-response by peeking at request.state.

        try:
            response = await call_next(request)
        except Exception:
            duration_ms = round((time.monotonic() - start) * 1000, 1)
            logger.error(
                "request_failed",
                method=request.method,
                path=request.url.path,
                duration_ms=duration_ms,
                request_id=request_id,
                exc_info=True,
            )
            raise

        duration_ms = round((time.monotonic() - start) * 1000, 1)

        # Extract user_id if the endpoint set it on request.state
        user_id = getattr(request.state, "user_id", None)

        logger.info(
            "request_completed",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=duration_ms,
            user_id=user_id,
            request_id=request_id,
        )

        response.headers["X-Request-ID"] = request_id
        return response
