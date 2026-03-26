"""Tests for weekly promo report helpers and promo-first matching engine."""

import sys
from pathlib import Path
from datetime import date

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.promo_reports import build_empty_promo_response, compute_promo_week
from app.models.enums import LoyaltyStatus, PromoBucket, PromoReportStatus
from scripts.promo_reports.promo_candidate_generation import (
    _compute_brand_bonus,
    _compute_score,
    BUCKET_LABELS,
    BUCKET_SIZES,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

class _FakePromoItem:
    """Minimal PromoItem stand-in for unit tests."""
    def __init__(self, **kwargs):
        self.display_name = kwargs.get("display_name", "Test Product")
        self.display_mechanism = kwargs.get("display_mechanism", "-25%")
        self.display_description = kwargs.get("display_description", "")
        self.display_savings_label = kwargs.get("display_savings_label", "")
        self.display_unit_price = kwargs.get("display_unit_price", None)
        self.original_price = kwargs.get("original_price", 4.00)
        self.promo_price = kwargs.get("promo_price", 3.00)
        self.savings_amount = kwargs.get("savings_amount", 1.00)
        self.min_purchase_qty = kwargs.get("min_purchase_qty", 1)
        self.promo_depth = kwargs.get("promo_depth", 25.0)
        self.granular_category = kwargs.get("granular_category", "Cola")
        self.source_retailer = kwargs.get("source_retailer", "colruyt")
        self.source_type = kwargs.get("source_type", "folder")
        self.page_number = kwargs.get("page_number", None)
        self.promo_folder_url = kwargs.get("promo_folder_url", None)
        self.validity_start = kwargs.get("validity_start", date(2026, 3, 24))
        self.validity_end = kwargs.get("validity_end", date(2026, 3, 30))


def _loyal_profile():
    return {
        "total_purchase_events": 9,
        "average_days_between": 14,
        "avg_price_paid": 0.43,
        "total_spend": 3.87,
        "brand_tally": {"everyday": 9},
        "loyalty_status": LoyaltyStatus.STRICTLY_LOYAL.value,
        "preferred_brand": "everyday",
        "is_premium_buyer": False,
        "last_purchase_date": "2026-02-21",
        "restock_urgency": 1.43,
    }


def _agnostic_profile():
    return {
        "total_purchase_events": 8,
        "average_days_between": 24,
        "avg_price_paid": 1.38,
        "total_spend": 10.10,
        "brand_tally": {"doritos": 3, "cheetos": 2, "lay's": 1},
        "loyalty_status": LoyaltyStatus.BRAND_AGNOSTIC.value,
        "preferred_brand": None,
        "is_premium_buyer": True,
        "last_purchase_date": "2026-02-21",
        "restock_urgency": 1.25,
    }


# ---------------------------------------------------------------------------
# Tests: promo week
# ---------------------------------------------------------------------------

def test_compute_promo_week_includes_iso_fields():
    week = compute_promo_week(date(2026, 3, 16))
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


# ---------------------------------------------------------------------------
# Tests: brand bonus scoring
# ---------------------------------------------------------------------------

def test_brand_bonus_strictly_loyal_match():
    promo = _FakePromoItem(display_name="Everyday Cola Zero 1.5L")
    bonus = _compute_brand_bonus(promo, _loyal_profile())
    assert bonus == 1.0


def test_brand_bonus_no_match():
    promo = _FakePromoItem(display_name="Coca-Cola Zero 1.5L")
    bonus = _compute_brand_bonus(promo, _loyal_profile())
    assert bonus == 0.0


def test_brand_bonus_partial_match_in_tally():
    promo = _FakePromoItem(display_name="Doritos Sweet Chili 200g")
    bonus = _compute_brand_bonus(promo, _agnostic_profile())
    assert bonus == 0.3


# ---------------------------------------------------------------------------
# Tests: score computation
# ---------------------------------------------------------------------------

def test_compute_score_loyal_profile():
    promo = _FakePromoItem(display_name="Everyday Cola Zero 1.5L", promo_depth=50.0)
    score, match_type = _compute_score(promo, _loyal_profile())
    assert match_type == "loyal"
    assert score > 0


def test_compute_score_agnostic_profile():
    promo = _FakePromoItem(display_name="Unknown Brand Chips", promo_depth=30.0)
    score, match_type = _compute_score(promo, _agnostic_profile())
    assert match_type == "agnostic"
    assert score > 0


def test_score_higher_for_matching_brand():
    promo_match = _FakePromoItem(display_name="Everyday Cola Zero 1.5L", promo_depth=25.0)
    promo_no_match = _FakePromoItem(display_name="Unknown Cola 1.5L", promo_depth=25.0)
    score_match, _ = _compute_score(promo_match, _loyal_profile())
    score_no_match, _ = _compute_score(promo_no_match, _loyal_profile())
    assert score_match > score_no_match


# ---------------------------------------------------------------------------
# Tests: bucket configuration
# ---------------------------------------------------------------------------

def test_bucket_sizes_sum_to_15():
    assert sum(BUCKET_SIZES.values()) == 15


def test_all_buckets_have_labels():
    for bucket in PromoBucket:
        assert bucket in BUCKET_LABELS
