"""Structured logging configuration with Axiom and Sentry integration.

Configures structlog for JSON output with optional forwarding to:
- Axiom (via axiom-py) for centralized log aggregation
- Sentry (via sentry-sdk) for error tracking

Environment variables:
    AXIOM_API_TOKEN: Axiom API token (optional, falls back to stdout)
    AXIOM_DATASET: Axiom dataset name (optional, falls back to stdout)
    SENTRY_DSN: Sentry DSN for error tracking (optional)
"""

import logging
import os
import sys

import structlog


def setup_logging() -> None:
    """Configure structlog with JSON rendering and optional Axiom/Sentry."""
    _setup_axiom()
    _setup_sentry()
    _configure_structlog()


def _setup_axiom() -> None:
    """Set up Axiom log handler if credentials are present."""
    token = os.environ.get("AXIOM_API_TOKEN", "")
    dataset = os.environ.get("AXIOM_DATASET", "")

    if not token or not dataset:
        return

    try:
        from axiom_py import Client
        from axiom_py.logging import AxiomHandler

        client = Client(token=token)
        handler = AxiomHandler(client, dataset)
        handler.setLevel(logging.INFO)

        root = logging.getLogger()
        root.addHandler(handler)
    except Exception as exc:
        # Don't crash the app if Axiom setup fails
        print(f"Warning: Axiom handler setup failed: {exc}", file=sys.stderr)


def _setup_sentry() -> None:
    """Initialize Sentry SDK if SENTRY_DSN is set."""
    dsn = os.environ.get("SENTRY_DSN", "")
    if not dsn:
        return

    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

        sentry_sdk.init(
            dsn=dsn,
            integrations=[
                FastApiIntegration(),
                SqlalchemyIntegration(),
            ],
            traces_sample_rate=0.1,
            send_default_pii=False,
        )
    except Exception as exc:
        print(f"Warning: Sentry init failed: {exc}", file=sys.stderr)


def _configure_structlog() -> None:
    """Wire structlog to emit JSON via the stdlib logging root."""
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(),
        ],
    )

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)

    root = logging.getLogger()
    # Remove default handlers to avoid duplicate plain-text output
    root.handlers = [
        h
        for h in root.handlers
        if not isinstance(h, logging.StreamHandler) or h.stream != sys.stderr
    ]
    root.addHandler(stream_handler)
    root.setLevel(logging.INFO)

    # Quiet noisy third-party loggers
    for name in ("uvicorn", "uvicorn.access", "uvicorn.error", "sqlalchemy.engine"):
        logging.getLogger(name).setLevel(logging.WARNING)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a bound structlog logger, optionally named."""
    return structlog.get_logger(name)
