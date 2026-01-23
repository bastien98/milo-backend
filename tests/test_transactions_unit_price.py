"""Test that /transactions endpoint includes unit_price in response."""
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.transaction import Transaction
from app.models.enums import Category
from datetime import date


@pytest.mark.asyncio
async def test_transaction_list_includes_unit_price(
    client: AsyncClient,
    db_session: AsyncSession,
    auth_headers: dict,
    test_user,
):
    """Test that transaction list response includes unit_price field."""
    # Create a test transaction with explicit unit_price
    transaction = Transaction(
        user_id=test_user.id,
        store_name="Test Store",
        item_name="Test Item",
        item_price=3.00,
        quantity=2,
        unit_price=1.50,
        category=Category.PANTRY,
        date=date.today(),
        health_score=3,
    )
    db_session.add(transaction)
    await db_session.commit()
    await db_session.refresh(transaction)

    # Fetch transactions via API
    response = await client.get("/v1/transactions", headers=auth_headers)

    assert response.status_code == 200
    data = response.json()

    assert "transactions" in data
    assert len(data["transactions"]) > 0

    # Verify unit_price is in the response
    transaction_data = data["transactions"][0]
    assert "unit_price" in transaction_data
    assert transaction_data["unit_price"] == 1.50
    assert transaction_data["item_price"] == 3.00
    assert transaction_data["quantity"] == 2


@pytest.mark.asyncio
async def test_transaction_detail_includes_unit_price(
    client: AsyncClient,
    db_session: AsyncSession,
    auth_headers: dict,
    test_user,
):
    """Test that individual transaction response includes unit_price field."""
    # Create a test transaction
    transaction = Transaction(
        user_id=test_user.id,
        store_name="Test Store",
        item_name="Single Item",
        item_price=5.99,
        quantity=1,
        unit_price=5.99,
        category=Category.DAIRY_EGGS,
        date=date.today(),
        health_score=4,
    )
    db_session.add(transaction)
    await db_session.commit()
    await db_session.refresh(transaction)

    # Fetch transaction by ID via API
    response = await client.get(
        f"/v1/transactions/{transaction.id}",
        headers=auth_headers
    )

    assert response.status_code == 200
    data = response.json()

    # Verify unit_price is in the response
    assert "unit_price" in data
    assert data["unit_price"] == 5.99
    assert data["item_price"] == 5.99
    assert data["quantity"] == 1
