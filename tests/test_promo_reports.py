"""Tests for weekly promo report helpers and deterministic assembly."""

import sys
from pathlib import Path
from datetime import date

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.promo_reports import build_empty_promo_response
from app.models.enums import PromoReportStatus
from scripts.promo_reports.promo_candidate_generation import (
    _compute_promo_week,
    _is_display_eligible_promo,
    _build_candidate_items,
    _get_emoji_for_category,
    _get_store_color,
    _merge_annotations,
)


def _base_promo() -> dict:
    return {
        "normalized_name": "coca cola zero",
        "original_description": "Coca-Cola Zero 1.5L",
        "source_retailer": "carrefour",
        "promo_mechanism": "1+1 Gratis",
        "original_price": 4.20,
        "promo_price": 2.10,
        "validity_start": "2026-03-16",
        "validity_end": "2026-03-22",
        "validity_start_epoch": 20260316,
        "validity_end_epoch": 20260322,
    }


def test_display_eligible_promo_accepts_active_complete_promos():
    promo = _base_promo()
    assert _is_display_eligible_promo(promo, report_date_epoch=20260318) is True


def test_display_eligible_promo_rejects_missing_mechanism():
    promo = _base_promo()
    promo["promo_mechanism"] = ""
    assert _is_display_eligible_promo(promo, report_date_epoch=20260318) is False


def test_display_eligible_promo_rejects_invalid_pricing():
    promo = _base_promo()
    promo["promo_price"] = 5.00
    assert _is_display_eligible_promo(promo, report_date_epoch=20260318) is False


def test_display_eligible_promo_rejects_inactive_promos():
    promo = _base_promo()
    assert _is_display_eligible_promo(promo, report_date_epoch=20260325) is False


def test_compute_promo_week_includes_iso_fields():
    week = _compute_promo_week(date(2026, 3, 16))
    assert week == {
        "start": "16/03",
        "end": "22/03",
        "label": "Week 12",
        "iso_year": 2026,
        "iso_week": 12,
    }


def test_empty_response_exposes_status_and_message():
    response = build_empty_promo_response(
        report_status=PromoReportStatus.NO_REPORT_AVAILABLE,
        message="This week's deals are not ready yet.",
        report_date=date(2026, 3, 16),
    )
    assert response["report_status"] == PromoReportStatus.NO_REPORT_AVAILABLE.value
    assert response["message"] == "This week's deals are not ready yet."
    assert response["deal_count"] == 0
    assert response["promo_week"]["iso_week"] == 12


# --- New candidate-related tests ---


def test_get_emoji_for_category():
    assert _get_emoji_for_category("Plant-based Milk", "Dairy") == "🥛"
    assert _get_emoji_for_category("Belgian Beer", "Alcohol") == "🍺"
    assert _get_emoji_for_category("Unknown", "") == "🛒"


def test_get_store_color():
    assert _get_store_color("Colruyt") == "🟧"
    assert _get_store_color("Delhaize") == "🟩"
    assert _get_store_color("Albert Heijn") == "🟨"
    assert _get_store_color("SomeUnknownStore") == "⬜"


def _sample_promo_results():
    return {
        "milk": [
            {
                "item_key": "abc123",
                "normalized_name": "milk",
                "original_description": "Whole Milk 1L",
                "brand": "Alpro",
                "granular_category": "Milk",
                "parent_category": "Dairy",
                "original_price": 2.50,
                "promo_price": 1.50,
                "promo_mechanism": "-40%",
                "validity_start": "17/03",
                "validity_end": "23/03",
                "source_retailer": "Colruyt",
                "page_number": 5.0,
                "promo_folder_url": "https://example.com/folder",
            },
        ],
        "bread": [
            {
                "item_key": "def456",
                "normalized_name": "bread",
                "original_description": "Whole Wheat Bread",
                "brand": "Private Label",
                "granular_category": "Bread",
                "parent_category": "Bakery",
                "original_price": 3.00,
                "promo_price": 2.00,
                "promo_mechanism": "1+1 Gratis",
                "validity_start": "17/03",
                "validity_end": "23/03",
                "source_retailer": "Delhaize",
                "page_number": None,
                "promo_folder_url": None,
            },
        ],
    }


def _sample_interest_items():
    return [
        {
            "normalized_name": "milk",
            "metrics": {
                "restock_urgency": 1.8,
                "purchase_frequency_days": 12,
                "avg_unit_price": 2.30,
            },
        },
        {
            "normalized_name": "bread",
            "metrics": {
                "restock_urgency": 0.5,
                "purchase_frequency_days": 7,
                "avg_unit_price": 2.80,
            },
        },
    ]


def test_build_candidate_items_creates_correct_structure():
    candidates = _build_candidate_items(_sample_promo_results(), _sample_interest_items())
    assert len(candidates) == 2

    milk = next(c for c in candidates if c["item_key"] == "abc123")
    assert milk["brand"] == "Alpro"
    assert milk["product_name"] == "Whole Milk 1L"
    assert milk["savings"] == 1.00
    assert milk["discount_percentage"] == 40
    assert milk["store_name"] == "Colruyt"
    assert milk["store_color"] == "🟧"
    assert milk["emoji"] == "🥛"
    assert milk["page_number"] == 5  # coerced from float
    assert milk["restock_urgency"] == 1.8
    assert milk["reason"] == ""  # not yet annotated


def test_build_candidate_items_deduplicates_by_item_key():
    promo_results = _sample_promo_results()
    # Add duplicate
    promo_results["milk"].append(promo_results["milk"][0])
    candidates = _build_candidate_items(promo_results, _sample_interest_items())
    assert len(candidates) == 2


def test_merge_annotations():
    candidates = [
        {"item_key": "abc123", "reason": ""},
        {"item_key": "def456", "reason": ""},
    ]
    annotations = {
        "item_annotations": [
            {"item_key": "abc123", "reason": "You buy this every 12 days."},
            {"item_key": "def456", "reason": "Great deal on bread."},
        ],
    }
    _merge_annotations(candidates, annotations)
    assert candidates[0]["reason"] == "You buy this every 12 days."
    assert candidates[1]["reason"] == "Great deal on bread."


def test_merge_annotations_handles_missing_keys():
    candidates = [
        {"item_key": "abc123", "reason": ""},
    ]
    annotations = {
        "item_annotations": [
            {"item_key": "unknown_key", "reason": "Should not match."},
        ],
    }
    _merge_annotations(candidates, annotations)
    assert candidates[0]["reason"] == ""
