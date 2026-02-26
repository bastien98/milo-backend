"""Basic tests to verify CI pipeline works."""
import pytest


def test_imports():
    """Verify core app modules can be imported."""
    from app.main import app
    assert app is not None


def test_app_has_routes():
    """Verify the FastAPI app has registered routes."""
    from app.main import app
    routes = [r.path for r in app.routes]
    assert "/health" in routes or "/v1/health" in routes or any("/health" in r for r in routes)


def test_models_import():
    """Verify SQLAlchemy models can be imported."""
    from app.models.user import User
    from app.models.transaction import Transaction
    from app.models.receipt import Receipt
    assert User is not None
    assert Transaction is not None
    assert Receipt is not None


def test_schemas_import():
    """Verify Pydantic schemas can be imported."""
    from app.schemas import receipt as receipt_schemas
    assert receipt_schemas is not None
