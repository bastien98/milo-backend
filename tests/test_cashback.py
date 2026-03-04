"""Tests for the progressive cashback calculation."""

import sys
from pathlib import Path

# Ensure app is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from app.services.cashback_service import CashbackService


class TestCalculateCashback:
    """Test calculate_cashback() against reference test vectors."""

    def test_ten_euros(self):
        amount, rate = CashbackService.calculate_cashback(10.00)
        assert amount == 0.05
        assert round(rate, 4) == 0.0050

    def test_fifty_euros(self):
        amount, rate = CashbackService.calculate_cashback(50.00)
        assert amount == 0.25
        assert round(rate, 4) == 0.0050

    def test_hundred_euros(self):
        amount, rate = CashbackService.calculate_cashback(100.00)
        assert amount == 0.53
        assert round(rate, 4) == 0.0053

    def test_two_hundred_euros(self):
        amount, rate = CashbackService.calculate_cashback(200.00)
        assert amount == 1.15
        assert round(rate, 4) == 0.0057  # 1.15 / 200 = 0.00575

    def test_five_fifty_euros(self):
        amount, rate = CashbackService.calculate_cashback(550.00)
        assert amount == 4.13
        assert round(rate, 4) == 0.0075

    def test_six_hundred_euros(self):
        amount, rate = CashbackService.calculate_cashback(600.00)
        assert amount == 4.63
        assert round(rate, 4) == 0.0077


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
        assert amount == 0.0  # 0.01 * 0.005 = 0.00005 → rounds to 0.00
        assert rate == 0.0

    def test_one_thousand_euros(self):
        """€1000 — segments 1–11 at progressive rates, rest at 1% cap."""
        amount, rate = CashbackService.calculate_cashback(1000.00)
        # Segments 1-11 (€550): 4.13
        # Remaining €450 at 1%: 4.50
        # Total: 8.63
        assert amount == 8.63
        assert round(rate, 4) == 0.0086

    def test_exactly_at_cap_boundary(self):
        """€550 is exactly 11 segments — the last segment hits 1% cap."""
        amount, _ = CashbackService.calculate_cashback(550.00)
        assert amount == 4.13

    def test_just_over_cap(self):
        """€550.01 — one cent beyond the cap boundary, still at 1%."""
        amount, _ = CashbackService.calculate_cashback(550.01)
        assert amount == 4.13  # 0.01 * 0.01 = 0.0001 → rounds same


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
        segments = CashbackService.calculate_cashback_segments(75.00)
        assert len(segments) == 2
        assert segments[0]["rate"] == 0.005
        assert segments[1]["rate"] == 0.0055

    def test_empty_for_zero(self):
        segments = CashbackService.calculate_cashback_segments(0.0)
        assert segments == []

    def test_empty_for_negative(self):
        segments = CashbackService.calculate_cashback_segments(-10.0)
        assert segments == []

    def test_segment_cashback_sums_close_to_total(self):
        """Sum of individual segment cashbacks should be within 1 cent of total.

        Segment cashbacks are rounded to 4dp individually, while the total is
        rounded to 2dp from the unrounded sum, so a tiny difference is expected.
        """
        total = 350.00
        segments = CashbackService.calculate_cashback_segments(total)
        segment_sum = round(sum(s["cashback"] for s in segments), 2)
        total_cashback, _ = CashbackService.calculate_cashback(total)
        assert abs(segment_sum - total_cashback) <= 0.01
