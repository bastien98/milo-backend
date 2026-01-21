import asyncio
from datetime import date, timedelta
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from app.main import app
from app.db.base import Base
from app.api.deps import get_db, get_current_db_user
from app.models.user import User
from app.models.transaction import Transaction
from app.models.enums import Category


# Use SQLite for testing
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(scope="session")
def event_loop():
    """Create an event loop for the entire test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="function")
async def test_engine():
    """Create a test database engine."""
    engine = create_async_engine(
        TEST_DATABASE_URL,
        echo=False,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def test_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """Create a test database session."""
    async_session_maker = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session_maker() as session:
        yield session


@pytest_asyncio.fixture(scope="function")
async def test_user(test_session: AsyncSession) -> User:
    """Create a test user."""
    user = User(
        id=str(uuid.uuid4()),
        firebase_uid="test_firebase_uid",
        email="test@example.com",
        display_name="Test User",
        is_active=True,
    )
    test_session.add(user)
    await test_session.commit()
    await test_session.refresh(user)
    return user


@pytest_asyncio.fixture(scope="function")
async def test_transactions(test_session: AsyncSession, test_user: User) -> list[Transaction]:
    """Create test transactions for the user."""
    today = date.today()
    transactions_data = [
        # Colruyt transactions
        {"store_name": "COLRUYT", "item_name": "Melk", "item_price": 1.29, "category": Category.DAIRY_EGGS, "date": today - timedelta(days=1), "health_score": 4},
        {"store_name": "COLRUYT", "item_name": "Brood", "item_price": 2.49, "category": Category.BAKERY, "date": today - timedelta(days=1), "health_score": 3},
        {"store_name": "COLRUYT", "item_name": "Kipfilet", "item_price": 7.99, "category": Category.MEAT_FISH, "date": today - timedelta(days=1), "health_score": 4},
        {"store_name": "COLRUYT", "item_name": "Appels", "item_price": 3.49, "category": Category.FRESH_PRODUCE, "date": today - timedelta(days=3), "health_score": 5},
        {"store_name": "COLRUYT", "item_name": "Bananen", "item_price": 1.99, "category": Category.FRESH_PRODUCE, "date": today - timedelta(days=3), "health_score": 5},
        # Aldi transactions
        {"store_name": "ALDI", "item_name": "Pasta", "item_price": 0.99, "category": Category.PANTRY, "date": today - timedelta(days=5), "health_score": 3},
        {"store_name": "ALDI", "item_name": "Tomatensaus", "item_price": 1.49, "category": Category.PANTRY, "date": today - timedelta(days=5), "health_score": 3},
        {"store_name": "ALDI", "item_name": "Kaas", "item_price": 4.99, "category": Category.DAIRY_EGGS, "date": today - timedelta(days=5), "health_score": 3},
        {"store_name": "ALDI", "item_name": "Bier (6-pack)", "item_price": 5.99, "category": Category.ALCOHOL, "date": today - timedelta(days=7), "health_score": 0},
        # Carrefour transactions
        {"store_name": "CARREFOUR", "item_name": "Chips", "item_price": 2.99, "category": Category.SNACKS_SWEETS, "date": today - timedelta(days=10), "health_score": 1},
        {"store_name": "CARREFOUR", "item_name": "Cola", "item_price": 1.99, "category": Category.DRINKS_SOFT, "date": today - timedelta(days=10), "health_score": 1},
        {"store_name": "CARREFOUR", "item_name": "Water (6x1.5L)", "item_price": 3.49, "category": Category.DRINKS_WATER, "date": today - timedelta(days=10), "health_score": 5},
        {"store_name": "CARREFOUR", "item_name": "Tandpasta", "item_price": 2.49, "category": Category.PERSONAL_CARE, "date": today - timedelta(days=14), "health_score": None},
        {"store_name": "CARREFOUR", "item_name": "Schoonmaakmiddel", "item_price": 3.99, "category": Category.HOUSEHOLD, "date": today - timedelta(days=14), "health_score": None},
        # More transactions for better statistics
        {"store_name": "COLRUYT", "item_name": "Yoghurt", "item_price": 2.99, "category": Category.DAIRY_EGGS, "date": today - timedelta(days=20), "health_score": 4},
        {"store_name": "COLRUYT", "item_name": "Eieren", "item_price": 3.29, "category": Category.DAIRY_EGGS, "date": today - timedelta(days=20), "health_score": 4},
        {"store_name": "ALDI", "item_name": "Pizza Diepvries", "item_price": 2.99, "category": Category.FROZEN, "date": today - timedelta(days=25), "health_score": 2},
        {"store_name": "ALDI", "item_name": "Lasagne Ready Meal", "item_price": 4.49, "category": Category.READY_MEALS, "date": today - timedelta(days=25), "health_score": 2},
    ]

    transactions = []
    for data in transactions_data:
        t = Transaction(
            id=str(uuid.uuid4()),
            user_id=test_user.id,
            **data
        )
        test_session.add(t)
        transactions.append(t)

    await test_session.commit()
    for t in transactions:
        await test_session.refresh(t)

    return transactions


@pytest_asyncio.fixture(scope="function")
async def client(
    test_session: AsyncSession,
    test_user: User,
    test_transactions: list[Transaction],
) -> AsyncGenerator[AsyncClient, None]:
    """Create a test client with mocked dependencies."""

    async def override_get_db():
        yield test_session

    async def override_get_current_db_user():
        return test_user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_db_user] = override_get_current_db_user

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test"
    ) as ac:
        yield ac

    app.dependency_overrides.clear()
