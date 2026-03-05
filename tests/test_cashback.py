"""Tests for the progressive cashback calculation."""

import sys
from pathlib import Path

# Ensure app is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from app.services.cashback_service import CashbackService


class TestCalculateCashback:
    """Test calculate_cashback() against reference test vectors.

    Tiers:
      €0–€80:   0.50%
      €80–€160:  0.60%
      €160–€240: 0.70%
      €240–€320: 0.80%
      €320–€400: 0.90%
      €400–€500: 1.00%
    Cap: €500 (no cashback on spending above €500).
    """

    def test_ten_euros(self):
        # 10 × 0.50% = 0.05
        amount, rate = CashbackService.calculate_cashback(10.00)
        assert amount == 0.05
        assert round(rate, 4) == 0.0050

    def test_eighty_euros(self):
        # Full first tier: 80 × 0.50% = 0.40
        amount, rate = CashbackService.calculate_cashback(80.00)
        assert amount == 0.40
        assert round(rate, 4) == 0.0050

    def test_hundred_euros(self):
        # 80 × 0.50% + 20 × 0.60% = 0.40 + 0.12 = 0.52
        amount, rate = CashbackService.calculate_cashback(100.00)
        assert amount == 0.52
        assert round(rate, 4) == 0.0052

    def test_two_hundred_euros(self):
        # 80 × 0.50% + 80 × 0.60% + 40 × 0.70% = 0.40 + 0.48 + 0.28 = 1.16
        amount, rate = CashbackService.calculate_cashback(200.00)
        assert amount == 1.16
        assert round(rate, 4) == 0.0058

    def test_two_fifty_euros(self):
        # 80×0.50% + 80×0.60% + 80×0.70% + 10×0.80% = 0.40+0.48+0.56+0.08 = 1.52
        amount, rate = CashbackService.calculate_cashback(250.00)
        assert amount == 1.52
        assert round(rate, 4) == 0.0061

    def test_four_hundred_euros(self):
        # 80×0.50% + 80×0.60% + 80×0.70% + 80×0.80% + 80×0.90%
        # = 0.40 + 0.48 + 0.56 + 0.64 + 0.72 = 2.80
        amount, rate = CashbackService.calculate_cashback(400.00)
        assert amount == 2.80
        assert round(rate, 4) == 0.0070

    def test_five_hundred_euros(self):
        # All tiers: 2.80 + 100×1.00% = 2.80 + 1.00 = 3.80
        amount, rate = CashbackService.calculate_cashback(500.00)
        assert amount == 3.80
        assert round(rate, 4) == 0.0076


class TestCap:
    """Test the €500 cap — spending above €500 earns no extra cashback."""

    def test_six_hundred_euros(self):
        # Capped at €500 eligible → same cashback as €500 = 3.80
        amount, rate = CashbackService.calculate_cashback(600.00)
        assert amount == 3.80
        # Effective rate is lower because denominator is 600
        assert round(rate, 4) == 0.0063

    def test_one_thousand_euros(self):
        # Capped at €500 eligible → 3.80
        amount, rate = CashbackService.calculate_cashback(1000.00)
        assert amount == 3.80
        assert round(rate, 4) == 0.0038


class TestEdgeCases:
    """Test edge cases for the cashback calculation."""

    def test_zero(self):
        amount, rate = CashbackService.calculate_cashback(0.0)
        assert amount == 0.0
        assert rate == 0.0

    def test_negative(self):
        amount, rate = CashbackService.calculate_cashback(-50.0)
        assert amount == 0.0
        assert rate == 0.0

    def test_one_cent(self):
        amount, rate = CashbackService.calculate_cashback(0.01)
        assert amount == 0.0  # 0.01 × 0.005 = 0.00005 → rounds to 0.00
        assert rate == 0.0


class TestSegmentBreakdown:
    """Test segment breakdown for preview display."""

    def test_single_segment(self):
        segments = CashbackService.calculate_cashback_segments(30.00)
        assert len(segments) == 1
        assert segments[0]["segment"] == 1
        assert segments[0]["rate"] == 0.005
        assert segments[0]["slice_start"] == 0
        assert segments[0]["slice_end"] == 30.0

    def test_two_segments(self):
        segments = CashbackService.calculate_cashback_segments(100.00)
        assert len(segments) == 2
        assert segments[0]["rate"] == 0.005
        assert segments[0]["slice_end"] == 80.0
        assert segments[1]["rate"] == 0.006
        assert segments[1]["slice_start"] == 80.0
        assert segments[1]["slice_end"] == 100.0

    def test_all_six_tiers(self):
        segments = CashbackService.calculate_cashback_segments(500.00)
        assert len(segments) == 6
        assert segments[5]["rate"] == 0.01
        assert segments[5]["slice_start"] == 400.0
        assert segments[5]["slice_end"] == 500.0

    def test_capped_at_500(self):
        # €700 should produce same segments as €500
        segments = CashbackService.calculate_cashback_segments(700.00)
        assert len(segments) == 6
        assert segments[5]["slice_end"] == 500.0

    def test_empty_for_zero(self):
        segments = CashbackService.calculate_cashback_segments(0.0)
        assert segments == []

    def test_empty_for_negative(self):
        segments = CashbackService.calculate_cashback_segments(-10.0)
        assert segments == []

    def test_segment_cashback_sums_close_to_total(self):
        """Sum of individual segment cashbacks should be within 1 cent of total."""
        total = 350.00
        segments = CashbackService.calculate_cashback_segments(total)
        segment_sum = round(sum(s["cashback"] for s in segments), 2)
        total_cashback, _ = CashbackService.calculate_cashback(total)
        assert abs(segment_sum - total_cashback) <= 0.01
