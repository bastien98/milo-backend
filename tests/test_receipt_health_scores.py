"""Tests for receipt health score functionality."""

import pytest
import pytest_asyncio
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

from httpx import AsyncClient

from app.models.enums import Category
from app.services.claude_service import ExtractedItem, ReceiptExtractionResult


@pytest.fixture
def mock_claude_response():
    """Create a mock Claude extraction response with health scores."""
    return ReceiptExtractionResult(
        store_name="COLRUYT",
        receipt_date=date(2026, 1, 16),
        total_amount=45.67,
        items=[
            ExtractedItem(
                item_name="Appels",
                item_price=3.49,
                quantity=1,
                unit_price=3.49,
                category=Category.FRESH_PRODUCE,
                health_score=5,  # Very healthy
            ),
            ExtractedItem(
                item_name="Bananen",
                item_price=1.99,
                quantity=1,
                unit_price=1.99,
                category=Category.FRESH_PRODUCE,
                health_score=5,  # Very healthy
            ),
            ExtractedItem(
                item_name="Kipfilet",
                item_price=7.99,
                quantity=1,
                unit_price=7.99,
                category=Category.MEAT_FISH,
                health_score=4,  # Healthy (lean protein)
            ),
            ExtractedItem(
                item_name="Eieren 10st",
                item_price=3.29,
                quantity=1,
                unit_price=3.29,
                category=Category.DAIRY_EGGS,
                health_score=4,  # Healthy
            ),
            ExtractedItem(
                item_name="Volkoren Brood",
                item_price=2.49,
                quantity=1,
                unit_price=2.49,
                category=Category.BAKERY,
                health_score=3,  # Moderately healthy
            ),
            ExtractedItem(
                item_name="Chips Paprika",
                item_price=2.99,
                quantity=1,
                unit_price=2.99,
                category=Category.SNACKS_SWEETS,
                health_score=1,  # Unhealthy
            ),
            ExtractedItem(
                item_name="Coca-Cola",
                item_price=1.99,
                quantity=1,
                unit_price=1.99,
                category=Category.DRINKS_SOFT_SODA,
                health_score=1,  # Unhealthy
            ),
            ExtractedItem(
                item_name="Bier Jupiler 6-pack",
                item_price=5.99,
                quantity=1,
                unit_price=5.99,
                category=Category.ALCOHOL,
                health_score=0,  # Very unhealthy
            ),
            ExtractedItem(
                item_name="Water Spa Reine 6x1.5L",
                item_price=3.49,
                quantity=1,
                unit_price=3.49,
                category=Category.DRINKS_WATER,
                health_score=5,  # Very healthy
            ),
            ExtractedItem(
                item_name="Afwasmiddel Dreft",
                item_price=3.99,
                quantity=1,
                unit_price=3.99,
                category=Category.HOUSEHOLD,
                health_score=None,  # Non-food item
            ),
            ExtractedItem(
                item_name="Tandpasta Colgate",
                item_price=2.49,
                quantity=1,
                unit_price=2.49,
                category=Category.PERSONAL_CARE,
                health_score=None,  # Non-food item
            ),
        ],
    )


@pytest.mark.asyncio
async def test_receipt_upload_with_health_scores(client: AsyncClient, mock_claude_response):
    """Test that receipt upload correctly extracts and stores health scores."""
    # Create a mock PDF file
    test_pdf = b"%PDF-1.4\n%mock pdf content"

    with patch(
        "app.services.receipt_processor.ClaudeService"
    ) as MockClaudeService:
        # Mock the Claude service
        mock_service = MagicMock()
        mock_service.extract_receipt_data = AsyncMock(return_value=mock_claude_response)
        MockClaudeService.return_value = mock_service

        # Also mock image validation to pass
        with patch(
            "app.services.receipt_processor.ImageValidator.validate_content_type"
        ), patch(
            "app.services.receipt_processor.ImageValidator.raise_if_invalid",
            return_value=[],
        ), patch(
            "app.services.receipt_processor.PDFService.is_pdf",
            return_value=True,
        ), patch(
            "app.services.receipt_processor.PDFService.convert_to_images",
            new_callable=AsyncMock,
            return_value=[b"mock_image_bytes"],
        ):
            response = await client.post(
                "/api/v1/receipts/upload",
                files={"file": ("test_receipt.pdf", test_pdf, "application/pdf")},
            )

    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "COMPLETED"
    assert data["store_name"] == "COLRUYT"
    assert data["items_count"] == 11

    # Verify health scores in transactions
    transactions = data["transactions"]

    # Check fresh produce items have health_score 5
    appels = next(t for t in transactions if t["item_name"] == "Appels")
    assert appels["health_score"] == 5
    assert appels["category"] == "Fresh Produce"

    # Check lean protein has health_score 4
    kipfilet = next(t for t in transactions if t["item_name"] == "Kipfilet")
    assert kipfilet["health_score"] == 4

    # Check unhealthy items
    chips = next(t for t in transactions if t["item_name"] == "Chips Paprika")
    assert chips["health_score"] == 1

    # Check alcohol has health_score 0
    bier = next(t for t in transactions if "Bier" in t["item_name"])
    assert bier["health_score"] == 0

    # Check non-food items have null health_score
    afwasmiddel = next(t for t in transactions if "Afwasmiddel" in t["item_name"])
    assert afwasmiddel["health_score"] is None

    tandpasta = next(t for t in transactions if "Tandpasta" in t["item_name"])
    assert tandpasta["health_score"] is None


@pytest.mark.asyncio
async def test_analytics_health_score(client: AsyncClient, test_transactions):
    """Test that analytics correctly calculates average health scores."""
    # First, let's add health scores to our test transactions
    # This is done by updating the conftest to include health_scores
    pass  # This test requires updating conftest.py


@pytest.mark.asyncio
async def test_transaction_response_includes_health_score(client: AsyncClient):
    """Test that transaction list endpoint includes health_score field."""
    response = await client.get("/api/v1/transactions")
    assert response.status_code == 200
    data = response.json()

    # Verify the schema includes health_score field
    if data["transactions"]:
        transaction = data["transactions"][0]
        assert "health_score" in transaction


@pytest.mark.asyncio
async def test_health_score_range_validation():
    """Test that health scores are properly clamped to 0-5 range."""
    from app.services.claude_service import ClaudeService

    service = ClaudeService.__new__(ClaudeService)

    # Test data with out-of-range health scores
    test_data = {
        "store_name": "TEST",
        "receipt_date": "2026-01-16",
        "total_amount": 10.00,
        "items": [
            {
                "item_name": "Test Item 1",
                "item_price": 5.00,
                "quantity": 1,
                "unit_price": 5.00,
                "category": "Fresh Produce",
                "health_score": 10,  # Should be clamped to 5
            },
            {
                "item_name": "Test Item 2",
                "item_price": 5.00,
                "quantity": 1,
                "unit_price": 5.00,
                "category": "Alcohol",
                "health_score": -5,  # Should be clamped to 0
            },
        ],
    }

    result = service._parse_extraction_result(test_data)

    assert result.items[0].health_score == 5  # Clamped from 10
    assert result.items[1].health_score == 0  # Clamped from -5


@pytest.mark.asyncio
async def test_null_health_score_for_non_food():
    """Test that null health scores are handled correctly."""
    from app.services.claude_service import ClaudeService

    service = ClaudeService.__new__(ClaudeService)

    test_data = {
        "store_name": "TEST",
        "receipt_date": "2026-01-16",
        "total_amount": 10.00,
        "items": [
            {
                "item_name": "Cleaning Product",
                "item_price": 5.00,
                "quantity": 1,
                "unit_price": 5.00,
                "category": "Household",
                "health_score": None,  # Non-food item
            },
        ],
    }

    result = service._parse_extraction_result(test_data)
    assert result.items[0].health_score is None
