"""Tests for compute_promo_depth."""

import pytest

from promo_folders_pipelines.promo_depth import compute_promo_depth


@pytest.mark.parametrize(
    "savings_amount, original_price, min_purchase_qty, expected",
    [
        # 1+1 Gratis @ €3
        (3.00, 3.00, 2, 50.0),
        # 2+1 Gratis @ €3
        (3.00, 3.00, 3, 33.3),
        # 12+6 Gratis @ €2.33
        (13.98, 2.33, 18, 33.3),
        # 2e aan Halve Prijs @ €3
        (1.50, 3.00, 2, 25.0),
        # 2e aan -70% @ €5
        (3.50, 5.00, 2, 35.0),
        # -25% single item
        (1.00, 4.00, 1, 25.0),
        # -25% Vanaf 2 Verpakkingen @ €4
        (1.00, 4.00, 2, 12.5),
        # Prijsverlaging €5 -> €3.75
        (1.25, 5.00, 1, 25.0),
        # 3 voor €5 with orig=2.50
        (2.50, 2.50, 3, 33.3),
    ],
)
def test_promo_depth(savings_amount, original_price, min_purchase_qty, expected):
    assert compute_promo_depth(savings_amount, original_price, min_purchase_qty) == expected


def test_zero_original_price():
    assert compute_promo_depth(1.00, 0.0, 1) == 0.0


def test_zero_min_qty_clamps_to_zero():
    assert compute_promo_depth(1.00, 4.00, 0) == 0.0


def test_clamp_above_100():
    # savings exceeding total cost should clamp to 100
    assert compute_promo_depth(10.00, 3.00, 1) == 100.0


def test_negative_savings():
    assert compute_promo_depth(-1.00, 4.00, 1) == 0.0
