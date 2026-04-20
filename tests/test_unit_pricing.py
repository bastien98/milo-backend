"""Tests for unit_pricing.compute_unit_price / validate_pack_size / is_displayable.

Covers the post-promo effective unit price formula across every mechanism type
we've seen in production extractions.
"""

import pytest

from promo_folders_pipelines.unit_pricing import (
    compute_unit_price,
    is_displayable,
    parse_legacy_display_unit_price,
    validate_pack_size,
)


# ---------------------------------------------------------------------------
# Helpers for the mechanism-driven scenarios
# ---------------------------------------------------------------------------

def _run(
    promo_price,
    original_price,
    min_qty,
    savings,
    pack_value,
    pack_unit,
    pack_count=1,
    display_name="irrelevant",
    granular_category="Other",
):
    return compute_unit_price(
        promo_price=promo_price,
        original_price=original_price,
        min_purchase_qty=min_qty,
        savings_amount=savings,
        pack_size_value=pack_value,
        pack_size_unit=pack_unit,
        pack_count=pack_count,
        display_name=display_name,
        granular_category=granular_category,
    )


# ---------------------------------------------------------------------------
# Simple price reductions (-X%, Prijsverlaging) — effective == promo_price / size
# ---------------------------------------------------------------------------


def test_minus_25_single_item():
    # original=€4, promo=€3 (already discounted), 1kg, savings=€1
    r = _run(promo_price=3.00, original_price=4.00, min_qty=1, savings=1.00,
             pack_value=1, pack_unit="kg")
    assert r.quality == "high"
    assert r.unit_price_unit == "kg"
    assert r.unit_price_value == pytest.approx(3.0, abs=0.01)
    assert r.display_unit_price == "€3.00/kg"


def test_minus_30_single_500g():
    # original=€5.99, promo=€4.19, 1.2kg, savings=€1.80
    r = _run(promo_price=4.19, original_price=5.99, min_qty=1, savings=1.80,
             pack_value=1.2, pack_unit="kg")
    assert r.unit_price_value == pytest.approx(3.49, abs=0.01)


def test_prijsverlaging_with_zero_savings():
    # Simple price cut where savings_amount defaults to 0 (promo already baked in)
    r = _run(promo_price=1.99, original_price=1.99, min_qty=1, savings=0.0,
             pack_value=800, pack_unit="g")
    assert r.unit_price_value == pytest.approx(2.49, abs=0.01)


# ---------------------------------------------------------------------------
# X+Y Gratis — matches Gemini's observed behavior exactly
# ---------------------------------------------------------------------------


def test_one_plus_one_gratis_skyr():
    # Skyr 200g @ 1+1 Gratis: shopper pays €2.29 for 400g
    r = _run(promo_price=2.29, original_price=2.29, min_qty=2, savings=2.29,
             pack_value=200, pack_unit="g")
    assert r.quality == "high"
    assert r.unit_price_value == pytest.approx(5.725, abs=0.01)
    # 5.725 → 5.72 via banker's rounding in f"{:.2f}"
    assert r.display_unit_price == "€5.72/kg"


def test_two_plus_one_gratis_chocoladerepen():
    # 2+1 Gratis, 4x46g pack @ €3.19
    r = _run(promo_price=3.19, original_price=3.19, min_qty=3, savings=3.19,
             pack_value=46, pack_unit="g", pack_count=4)
    # cost = 3.19*3 - 3.19 = 6.38; qty = 0.046*4*3 = 0.552 kg → 11.56/kg
    assert r.unit_price_value == pytest.approx(11.557, abs=0.05)
    assert r.display_unit_price == "€11.56/kg"


def test_twelve_plus_six_gratis():
    # 12+6 Gratis @ €2.33, 33cl beer blik → 18 packs, pay for 12
    r = _run(promo_price=2.33, original_price=2.33, min_qty=18, savings=13.98,
             pack_value=33, pack_unit="cl")
    # cost = 2.33*18 - 13.98 = 27.96; qty = 0.33 * 18 = 5.94 L → 4.71/L
    assert r.unit_price_value == pytest.approx(4.707, abs=0.01)
    assert r.unit_price_unit == "l"


# ---------------------------------------------------------------------------
# 2e aan Halve Prijs — pay for 1 full + 1 half = 1.5× promo_price
# ---------------------------------------------------------------------------


def test_second_half_price_yoghurt():
    # Yoghurt 500g @ 2e aan Halve Prijs, original=€3
    # cost = 3*2 - 1.5 = 4.50; qty = 0.5*2 = 1 kg → 4.50/kg
    r = _run(promo_price=3.00, original_price=3.00, min_qty=2, savings=1.50,
             pack_value=500, pack_unit="g")
    assert r.unit_price_value == pytest.approx(4.5, abs=0.01)


# ---------------------------------------------------------------------------
# -X% Vanaf N Verpakkingen — discount applies to all min_qty items
# ---------------------------------------------------------------------------


def test_minus_25_vanaf_2_verpakkingen():
    # -25% Vanaf 2 Verpakkingen: original=€4, promo=€3 (discounted), min=2, savings=€2
    r = _run(promo_price=3.00, original_price=4.00, min_qty=2, savings=2.00,
             pack_value=1, pack_unit="kg")
    # cost = 4*2 - 2 = 6; qty = 1*2 = 2 kg → 3/kg (matches promo_price)
    assert r.unit_price_value == pytest.approx(3.0, abs=0.01)


def test_minus_20_vanaf_3():
    # -20% Vanaf 3 Flessen: original=€2, promo=€1.60, min=3, savings=€1.20
    r = _run(promo_price=1.60, original_price=2.00, min_qty=3, savings=1.20,
             pack_value=75, pack_unit="cl")
    # cost = 2*3 - 1.20 = 4.80; qty = 0.75 * 3 = 2.25 L → 2.133/L
    assert r.unit_price_value == pytest.approx(2.133, abs=0.01)


# ---------------------------------------------------------------------------
# ± weight items — per-kg priced butcher/deli
# ---------------------------------------------------------------------------


def test_plus_minus_weight_spare_ribs():
    # "Gemarineerde Varkensribbetjes ± 500 g" — price is €8.29/kg already
    # Prompt tells Gemini to return value=1, unit="kg", count=1 for ± items.
    r = _run(promo_price=8.29, original_price=13.82, min_qty=1, savings=5.53,
             pack_value=1, pack_unit="kg",
             display_name="Gemarineerde Varkensribbetjes ± 500 g")
    # cost = 13.82 - 5.53 = 8.29; qty = 1 kg → 8.29/kg
    assert r.unit_price_value == pytest.approx(8.29, abs=0.01)
    assert r.display_unit_price == "€8.29/kg"


def test_plus_minus_weight_hamburger():
    # "Hamburger Van Tussenrib ± 300 g" @ -20%, promo=€13.59, orig=€16.99
    r = _run(promo_price=13.59, original_price=16.99, min_qty=1, savings=3.40,
             pack_value=1, pack_unit="kg",
             display_name="Hamburger Van Tussenrib ± 300 g")
    assert r.unit_price_value == pytest.approx(13.59, abs=0.01)


# ---------------------------------------------------------------------------
# Multi-pack drinks — pack_count > 1
# ---------------------------------------------------------------------------


def test_multipack_drinks_simple_discount():
    # 6 x 25 cl beer pack, simple price cut @ €3.49
    r = _run(promo_price=3.49, original_price=3.49, min_qty=1, savings=0.0,
             pack_value=25, pack_unit="cl", pack_count=6)
    # cost = 3.49; qty = 0.25 * 6 = 1.5 L → 2.33/L
    assert r.unit_price_value == pytest.approx(2.327, abs=0.01)
    assert r.unit_price_unit == "l"


def test_multipack_waterijsjes_2e_halve_prijs():
    # Waterijsjes 6x54ml @ 2e aan Halve Prijs, promo=€3.49, orig=€3.49
    r = _run(promo_price=3.49, original_price=3.49, min_qty=2, savings=1.745,
             pack_value=54, pack_unit="ml", pack_count=6)
    # cost = 3.49*2 - 1.745 = 5.235; qty = 0.054*6*2 = 0.648 L → 8.08/L
    assert r.unit_price_value == pytest.approx(8.08, abs=0.05)


# ---------------------------------------------------------------------------
# Countables: stuk, rol, capsule, tab, zakje, doekje
# ---------------------------------------------------------------------------


def test_capsules_simple_discount():
    # Box 12 capsules @ €3.99, -25% → promo=€2.99, orig=€3.99, savings=€1
    r = _run(promo_price=2.99, original_price=3.99, min_qty=1, savings=1.00,
             pack_value=12, pack_unit="capsule")
    # cost = 3.99 - 1.00 = 2.99; qty = 12 stuk → 0.2492/stuk
    assert r.unit_price_unit == "stuk"
    assert r.unit_price_value == pytest.approx(0.2492, abs=0.005)


def test_rol_multipack():
    # 4-pack toiletpapier 6 rollen @ €7.99 simple
    r = _run(promo_price=7.99, original_price=7.99, min_qty=1, savings=0.0,
             pack_value=6, pack_unit="rol", pack_count=4)
    # qty = 24 rol → 0.33/rol
    assert r.unit_price_unit == "rol"
    assert r.unit_price_value == pytest.approx(0.333, abs=0.01)


# ---------------------------------------------------------------------------
# Fallbacks — wine / beer defaults when size missing
# ---------------------------------------------------------------------------


def test_wine_fallback_without_size_info():
    r = _run(promo_price=8.99, original_price=8.99, min_qty=1, savings=0.0,
             pack_value=None, pack_unit=None,
             display_name="Chateau X Grand Cru",
             granular_category="Red Wine")
    assert r.quality == "low"
    assert r.unit_price_unit == "l"
    # cost = 8.99; qty = 0.75 L → 11.99/L
    assert r.unit_price_value == pytest.approx(11.987, abs=0.05)


def test_beer_blik_fallback():
    r = _run(promo_price=0.89, original_price=0.89, min_qty=1, savings=0.0,
             pack_value=None, pack_unit=None,
             display_name="Jupiler Pils Blik",
             granular_category="Pilsners & Lagers")
    assert r.quality == "low"
    # cost = 0.89; qty = 0.33 L → 2.70/L
    assert r.unit_price_value == pytest.approx(2.697, abs=0.05)


def test_beer_fallback_skipped_when_no_blik_in_name():
    # Abbey beer without 'blik' keyword — won't fallback
    r = _run(promo_price=1.49, original_price=1.49, min_qty=1, savings=0.0,
             pack_value=None, pack_unit=None,
             display_name="Duvel Tripel",
             granular_category="Specialty & Abbey Beers")
    assert r.quality == "missing"
    assert r.unit_price_value is None


# ---------------------------------------------------------------------------
# Fallback when original_price is missing — quality='medium'
# ---------------------------------------------------------------------------


def test_missing_original_price_falls_back_to_promo():
    r = _run(promo_price=2.99, original_price=None, min_qty=1, savings=0.0,
             pack_value=500, pack_unit="g")
    assert r.quality == "medium"
    assert r.unit_price_value == pytest.approx(5.98, abs=0.01)


def test_zero_original_price_falls_back_to_promo():
    r = _run(promo_price=2.99, original_price=0.0, min_qty=1, savings=0.0,
             pack_value=500, pack_unit="g")
    assert r.quality == "medium"


# ---------------------------------------------------------------------------
# Invalid / missing inputs
# ---------------------------------------------------------------------------


def test_zero_promo_price_returns_missing():
    r = _run(promo_price=0.0, original_price=5.0, min_qty=1, savings=0.0,
             pack_value=500, pack_unit="g")
    assert r.quality == "missing"


def test_unknown_pack_unit_returns_invalid():
    r = _run(promo_price=1.99, original_price=1.99, min_qty=1, savings=0.0,
             pack_value=10, pack_unit="liter")  # not in conversion table
    assert r.quality == "invalid"
    assert any("unknown pack_size_unit" in w for w in r.warnings)


def test_over_stated_savings_returns_invalid():
    # Sanity: if savings > cost, we'd get negative actual_cost — catch it
    r = _run(promo_price=2.0, original_price=2.0, min_qty=1, savings=5.0,
             pack_value=500, pack_unit="g")
    assert r.quality == "invalid"


def test_missing_pack_size_non_wine_non_beer_returns_missing():
    r = _run(promo_price=5.99, original_price=5.99, min_qty=1, savings=0.0,
             pack_value=None, pack_unit=None,
             display_name="Assortiment Sauzen",
             granular_category="Other")
    assert r.quality == "missing"


def test_pack_count_defaults_to_one_on_none():
    r = _run(promo_price=2.00, original_price=2.00, min_qty=1, savings=0.0,
             pack_value=500, pack_unit="g", pack_count=None)
    assert r.quality == "high"
    assert r.unit_price_value == pytest.approx(4.0, abs=0.01)


# ---------------------------------------------------------------------------
# validate_pack_size — catches gross Gemini mis-extractions
# ---------------------------------------------------------------------------


def test_validate_matches_exact():
    assert validate_pack_size("Yoghurt 500 g", 500, "g") is None


def test_validate_matches_within_tolerance():
    assert validate_pack_size("Yoghurt 500 g", 498, "g") is None


def test_validate_catches_gross_mismatch():
    assert validate_pack_size("Yoghurt 500 g", 50, "g") is not None


def test_validate_belgian_decimal():
    assert validate_pack_size("Coca-Cola Zero 1,5 L", 1.5, "l") is None


def test_validate_cross_unit_match():
    # 75 cl = 0.75 L = 750 ml → same base unit, values match
    assert validate_pack_size("Fles Wijn 750 ml", 75, "cl") is None


def test_validate_null_inputs_return_none():
    assert validate_pack_size("foo 500g", None, "g") is None
    assert validate_pack_size("foo 500g", 500, None) is None


# ---------------------------------------------------------------------------
# is_displayable — the API correctness gate
# ---------------------------------------------------------------------------


def test_is_displayable_high_quality_passes():
    assert is_displayable(5.73, "kg", "high", "Skyr 200 g", 200, "g") is True


def test_is_displayable_medium_quality_passes():
    assert is_displayable(5.98, "kg", "medium", "Foo 500 g", 500, "g") is True


def test_is_displayable_low_quality_hidden():
    assert is_displayable(11.99, "l", "low", "Chateau X", None, None) is False


def test_is_displayable_insane_value_hidden():
    assert is_displayable(9999.0, "kg", "high", "Foo 1 g", 1, "g") is False


def test_is_displayable_validation_mismatch_hidden():
    # Gemini said 50 g but name shows 500 g
    assert is_displayable(20.0, "kg", "high", "Yoghurt 500 g", 50, "g") is False


def test_is_displayable_null_value_hidden():
    assert is_displayable(None, "kg", "high", "Foo", 500, "g") is False


# ---------------------------------------------------------------------------
# Legacy parser — for ad-hoc backfill if ever needed
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text,expected", [
    ("€0.84/L", (0.84, "l")),
    ("€12.50/kg", (12.50, "kg")),
    ("€0.55/stuk", (0.55, "stuk")),
])
def test_parse_legacy_display(text, expected):
    assert parse_legacy_display_unit_price(text) == expected


def test_parse_legacy_display_unparseable():
    assert parse_legacy_display_unit_price(None) is None
    assert parse_legacy_display_unit_price("") is None
    assert parse_legacy_display_unit_price("€0.84/ml") is None
