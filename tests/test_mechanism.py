"""Tests for the canonical promo-mechanism derivation layer."""

import pytest

from promo_folders_pipelines.mechanism import (
    ALL_KINDS,
    canonical_label,
    compute_savings,
    display_description,
    display_savings_label,
    infer_original_price,
    infer_promo_price,
    min_purchase_qty,
)


# ---------------------------------------------------------------------------
# canonical_label
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "kind, x, y, expected",
    [
        ("buy_x_get_y_free", 1, 1, "1+1 Gratis"),
        ("buy_x_get_y_free", 2, 1, "2+1 Gratis"),
        ("buy_x_get_y_free", 12, 6, "12+6 Gratis"),
        ("second_half_price", None, None, "2e aan Halve Prijs"),
        ("second_percent_off", 50, None, "2e aan -50%"),
        ("second_percent_off", 70, None, "2e aan -70%"),
        ("percent_off", 25, None, "-25%"),
        ("percent_off", 30, None, "-30%"),
        ("percent_off_from_n", 25, 2, "-25% Vanaf 2 Verpakkingen"),
        ("percent_off_from_n", 20, 3, "-20% Vanaf 3 Verpakkingen"),
        ("percent_off_from_n", 30, 12, "-30% Vanaf 12 Verpakkingen"),
        ("euro_off", 0.50, None, "€0.50 Korting"),
        ("euro_off", 1.25, None, "€1.25 Korting"),
        ("n_for_euro", 2, 5.00, "2 Voor €5.00"),
        ("n_for_euro", 3, 4.50, "3 Voor €4.50"),
        ("price_reduction", None, None, "Prijsverlaging"),
    ],
)
def test_canonical_label(kind, x, y, expected):
    assert canonical_label(kind, x, y) == expected


def test_canonical_label_all_kinds_produce_nonempty_fallback():
    # Even with missing params, every kind produces a sensible string.
    for kind in ALL_KINDS:
        result = canonical_label(kind, None, None)
        assert isinstance(result, str) and result


# ---------------------------------------------------------------------------
# min_purchase_qty
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "kind, x, y, expected",
    [
        ("buy_x_get_y_free", 1, 1, 2),
        ("buy_x_get_y_free", 2, 1, 3),
        ("buy_x_get_y_free", 12, 6, 18),
        ("second_half_price", None, None, 2),
        ("second_percent_off", 70, None, 2),
        ("percent_off", 25, None, 1),
        ("percent_off_from_n", 25, 2, 2),
        ("percent_off_from_n", 30, 12, 12),
        ("euro_off", 0.50, None, 1),
        ("n_for_euro", 3, 5.00, 3),
        ("price_reduction", None, None, 1),
    ],
)
def test_min_purchase_qty(kind, x, y, expected):
    assert min_purchase_qty(kind, x, y) == expected


def test_min_purchase_qty_never_below_one():
    assert min_purchase_qty("buy_x_get_y_free", None, None) == 1
    assert min_purchase_qty("n_for_euro", None, None) == 1
    assert min_purchase_qty("percent_off_from_n", 25, None) == 1


# ---------------------------------------------------------------------------
# compute_savings — covers the worked examples from the old prompt.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "kind, x, y, original_price, promo_price, stated_savings, expected",
    [
        # "1+1 gratis" @ €3.00: savings = 3.00
        ("buy_x_get_y_free", 1, 1, 3.00, 3.00, None, 3.00),
        # "2+1 gratis" @ €3.00: savings = 3.00
        ("buy_x_get_y_free", 2, 1, 3.00, 3.00, None, 3.00),
        # "12+6 gratis" @ €2.33: savings = 13.98
        ("buy_x_get_y_free", 12, 6, 2.33, 2.33, None, 13.98),
        # "2e aan halve prijs" @ €3.00: savings = 1.50
        ("second_half_price", None, None, 3.00, 3.00, None, 1.50),
        # "-25%" on single item @ €4.00: savings = 1.00
        ("percent_off", 25, None, 4.00, None, None, 1.00),
        # "-25% vanaf 2 verpakkingen" @ €4.00: savings = 2.00
        ("percent_off_from_n", 25, 2, 4.00, 4.00, None, 2.00),
        # "-20% vanaf 3 verpakkingen" @ €2.00: savings = 1.20
        ("percent_off_from_n", 20, 3, 2.00, 2.00, None, 1.20),
        # "€0.50 korting": savings = 0.50
        ("euro_off", 0.50, None, None, None, None, 0.50),
        # "3 voor €5" with original unit €2.00: savings = 1.00
        ("n_for_euro", 3, 5.00, 2.00, 2.00, None, 1.00),
        # price_reduction €5 -> €3.75: savings = 1.25
        ("price_reduction", None, None, 5.00, 3.75, None, 1.25),
    ],
)
def test_compute_savings(kind, x, y, original_price, promo_price, stated_savings, expected):
    assert compute_savings(kind, x, y, original_price, promo_price, stated_savings) == pytest.approx(expected, abs=0.01)


def test_compute_savings_stated_wins():
    # Printed "Bespaar €2.00" overrides mechanism-derived value.
    assert compute_savings("percent_off", 25, None, 4.00, None, 2.00) == 2.00


def test_compute_savings_missing_inputs_returns_none():
    assert compute_savings("percent_off", None, None, 4.00, None, None) is None
    assert compute_savings("buy_x_get_y_free", 1, 1, None, None, None) is None
    assert compute_savings("price_reduction", None, None, None, None, None) is None
    assert compute_savings("n_for_euro", 3, None, 2.00, None, None) is None


def test_compute_savings_negative_multi_pack_returns_none():
    # "3 voor €10" where unit original is €2.00 → 3*2 - 10 = -4 (the deal is worse than full price,
    # which shouldn't happen in practice; guard against negative savings).
    assert compute_savings("n_for_euro", 3, 10.00, 2.00, None, None) is None


# ---------------------------------------------------------------------------
# infer_original_price
# ---------------------------------------------------------------------------
def test_infer_original_price_percent_off():
    assert infer_original_price("percent_off", 25, None, 3.00, None) == 4.00
    assert infer_original_price("percent_off", 50, None, 2.50, None) == 5.00


def test_infer_original_price_buy_x_get_y_free_is_same():
    assert infer_original_price("buy_x_get_y_free", 1, 1, 3.00, None) == 3.00


def test_infer_original_price_euro_off_uses_stated_savings():
    assert infer_original_price("euro_off", None, None, 3.00, 0.50) == 3.50


def test_infer_original_price_euro_off_falls_back_to_x():
    assert infer_original_price("euro_off", 0.50, None, 3.00, None) == 3.50


def test_infer_original_price_returns_none_when_missing():
    assert infer_original_price("percent_off", None, None, 3.00, None) is None
    assert infer_original_price("euro_off", None, None, 3.00, None) is None
    assert infer_original_price("percent_off", 25, None, None, None) is None


# ---------------------------------------------------------------------------
# infer_promo_price
# ---------------------------------------------------------------------------
def test_infer_promo_price_percent_off():
    assert infer_promo_price("percent_off", 25, None, 4.00) == 3.00


def test_infer_promo_price_n_for_euro():
    assert infer_promo_price("n_for_euro", 3, 5.00, 2.00) == pytest.approx(1.67, abs=0.01)


def test_infer_promo_price_euro_off():
    assert infer_promo_price("euro_off", 0.50, None, 3.00) == 2.50


def test_infer_promo_price_buy_x_get_y_free_matches_original():
    assert infer_promo_price("buy_x_get_y_free", 1, 1, 3.00) == 3.00


# ---------------------------------------------------------------------------
# display_description
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "kind, x, y, expected_substring",
    [
        ("buy_x_get_y_free", 2, 1, "Koop er 2"),
        ("buy_x_get_y_free", 1, 1, "Koop er 1, krijg er 1 gratis"),
        ("second_half_price", None, None, "halve prijs"),
        ("percent_off", 25, None, "-25%"),
        ("percent_off_from_n", 25, 2, "Vanaf 2"),
        ("euro_off", 0.50, None, "€0.50"),
        ("n_for_euro", 3, 5.00, "3 voor €5.00"),
        ("price_reduction", None, None, "goedkoper"),
    ],
)
def test_display_description_contains_key_substring(kind, x, y, expected_substring):
    desc = display_description(kind, x, y)
    assert expected_substring in desc, f"{kind}({x},{y}) → {desc!r} missing {expected_substring!r}"


# ---------------------------------------------------------------------------
# display_savings_label
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "kind, x, y, savings, expected",
    [
        ("buy_x_get_y_free", 1, 1, 3.00, "1 Gratis Item"),
        ("buy_x_get_y_free", 2, 1, 3.00, "1 Gratis Item"),
        ("buy_x_get_y_free", 12, 6, 13.98, "6 Gratis Items"),
        ("second_half_price", None, None, 1.50, "2e aan Halve Prijs"),
        ("second_percent_off", 70, None, 3.50, "2e aan -70%"),
        ("percent_off", 25, None, 1.00, "Tot -25% Korting"),
        ("percent_off_from_n", 20, 3, 1.20, "Tot -20% Korting"),
        ("euro_off", 0.50, None, 0.50, "Bespaar €0.50"),
        ("n_for_euro", 3, 5.00, 1.00, "Bespaar €1.00"),
        ("price_reduction", None, None, 1.25, "Bespaar €1.25"),
    ],
)
def test_display_savings_label(kind, x, y, savings, expected):
    assert display_savings_label(kind, x, y, savings) == expected
