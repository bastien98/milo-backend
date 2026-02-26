import os
from unittest.mock import AsyncMock, patch

import pytest

os.environ.setdefault("TESTING", "true")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test_scandalicious")
os.environ.setdefault("FIREBASE_PROJECT_ID", "test-project")


@pytest.fixture
def mock_firebase_auth():
    """Mock Firebase token verification."""
    with patch("app.core.security.verify_firebase_token") as mock:
        mock.return_value = {
            "uid": "test-firebase-uid",
            "email": "test@example.com",
        }
        yield mock


@pytest.fixture
def mock_db_session():
    """Mock async database session."""
    session = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.close = AsyncMock()
    yield session
