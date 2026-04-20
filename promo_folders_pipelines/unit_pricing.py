"""
Deterministic unit-price computation for promo items.

Gemini extracts observable tokens (pack_size_value, pack_size_unit, pack_count).
This module computes the POST-PROMO EFFECTIVE unit price — i.e. the euro cost per
canonical unit (kg, L, stuk, rol) that a shopper actually pays when completing the
deal. This lets shoppers compare promotions of the same product across stores at a
glance, regardless of the underlying mechanism (X+Y gratis, 2e halve prijs, -25%
vanaf N, prijsverlaging, etc.).

Formula:
    actual_cost = original_price × min_purchase_qty − savings_amount
    total_qty   = pack_size_value_canonical × pack_count × min_purchase_qty
    effective_unit_price = actual_cost / total_qty

Pure functions, no I/O. Safe to unit-test in isolation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal, Optional

Quality = Literal["high", "medium", "low", "missing", "invalid"]

# Canonical units we surface to consumers. Everything gets normalised to one of these.
CANONICAL_UNITS = ("kg", "l", "stuk", "rol")

# g→kg, ml→l, cl→l, capsule/tab/doekje/zakje→stuk
_UNIT_CONVERSION: dict[str, tuple[str, float]] = {
    "g": ("kg", 0.001),
    "kg": ("kg", 1.0),
    "ml": ("l", 0.001),
    "cl": ("l", 0.01),
    "l": ("l", 1.0),
    "stuk": ("stuk", 1.0),
    "rol": ("rol", 1.0),
    "capsule": ("stuk", 1.0),
    "tab": ("stuk", 1.0),
    "doekje": ("stuk", 1.0),
    "zakje": ("stuk", 1.0),
}

# Category substrings that trigger the 75cl-wine fallback when pack size is missing.
_WINE_CATEGORIES = (
    "Red Wine", "White Wine", "Rosé Wine",
    "Champagne & Sparkling Wine", "Non-Alcoholic Wine",
)

# Category substrings that trigger the 33cl-beer fallback when "blik"/"can" is in the name.
_BEER_CATEGORIES = (
    "Pilsners & Lagers", "Specialty & Abbey Beers", "Fruit Beers & Geuze",
    "Non-Alcoholic Beers (0.0%)",
)

# Sanity bounds for €/unit values. A promo tile extracting €9999/kg is an arithmetic bug.
_MIN_UNIT_PRICE = 0.01
_MAX_UNIT_PRICE = 1000.0


@dataclass
class UnitPriceResult:
    unit_price_value: Optional[float] = None
    unit_price_unit: Optional[str] = None
    display_unit_price: Optional[str] = None
    quality: Quality = "missing"
    warnings: list[str] = field(default_factory=list)


def compute_unit_price(
    promo_price: Optional[float],
    original_price: Optional[float],
    min_purchase_qty: int,
    savings_amount: Optional[float],
    pack_size_value: Optional[float],
    pack_size_unit: Optional[str],
    pack_count: Optional[int],
    display_name: str,
    granular_category: str,
) -> UnitPriceResult:
    """Compute post-promo effective unit price the shopper actually pays per canonical unit.

    Quality:
      - 'high'    when original_price > 0 and Gemini gave a pack size.
      - 'medium'  when we fell back to promo_price for the original (extraction gap).
      - 'low'     when we fell back to a canonical 75cl/33cl default for wine/beer.
      - 'invalid' when inputs produce a non-sensible result.
      - 'missing' when nothing is recoverable.
    """
    result = UnitPriceResult()

    if promo_price is None or promo_price <= 0:
        return result

    min_qty = max(1, int(min_purchase_qty or 1))

    # Pick the best available reference price. If original is missing/zero we fall back
    # to promo_price (flagged medium quality) — the formula still produces the right
    # shape, just cannot account for savings that would've reduced the cost.
    if original_price and original_price > 0:
        reference_price = original_price
        reference_quality: Quality = "high"
    else:
        reference_price = promo_price
        reference_quality = "medium"

    actual_cost = reference_price * min_qty - (savings_amount or 0.0)

    # Primary path: Gemini extracted a pack size.
    if pack_size_value is not None and pack_size_value > 0 and pack_size_unit:
        canonical = _canonicalise(pack_size_value, pack_size_unit, pack_count or 1)
        if canonical is None:
            result.warnings.append(f"unknown pack_size_unit: {pack_size_unit!r}")
            result.quality = "invalid"
            return result
        canonical_unit, total_qty_per_pack_group = canonical
        total_qty = total_qty_per_pack_group * min_qty
        return _finalise(actual_cost, canonical_unit, total_qty, reference_quality, result)

    # Fallback path: no pack size from Gemini — use category + display_name heuristics.
    if _is_wine_category(granular_category):
        result.warnings.append("assumed 75cl wine (no pack size in Gemini output)")
        return _finalise(actual_cost, "l", 0.75 * min_qty, "low", result)

    if _is_beer_blik(granular_category, display_name):
        result.warnings.append("assumed 33cl beer blik (no pack size in Gemini output)")
        return _finalise(actual_cost, "l", 0.33 * min_qty, "low", result)

    # Nothing to compute from.
    return result


def _finalise(
    total_cost: float,
    canonical_unit: str,
    total_quantity: float,
    quality: Quality,
    result: UnitPriceResult,
) -> UnitPriceResult:
    if total_cost <= 0 or total_quantity <= 0:
        result.quality = "invalid"
        if total_cost <= 0:
            result.warnings.append("actual_cost <= 0 (likely over-estimated savings_amount)")
        if total_quantity <= 0:
            result.warnings.append("total_quantity <= 0")
        return result

    value = total_cost / total_quantity
    result.unit_price_value = round(value, 4)
    result.unit_price_unit = canonical_unit
    result.display_unit_price = _format_display(value, canonical_unit)
    result.quality = quality
    return result


def _canonicalise(
    pack_size_value: float,
    pack_size_unit: str,
    pack_count: int,
) -> Optional[tuple[str, float]]:
    """Return (canonical_unit, quantity_in_one_deal_group) or None if unit unknown.

    The returned quantity is for pack_size_value × pack_count — i.e. one "deal-group"
    unit (a multi-pack like "6 x 25 cl" is 6×25cl = 1.5L per unit). The caller
    multiplies by min_purchase_qty separately.
    """
    unit_key = (pack_size_unit or "").strip().lower()
    conv = _UNIT_CONVERSION.get(unit_key)
    if conv is None:
        return None
    canonical_unit, multiplier = conv
    total_qty = pack_size_value * multiplier * max(1, int(pack_count))
    return canonical_unit, total_qty


def _format_display(value: float, canonical_unit: str) -> str:
    unit_label = {"kg": "kg", "l": "L", "stuk": "stuk", "rol": "rol"}.get(
        canonical_unit, canonical_unit
    )
    return f"€{value:.2f}/{unit_label}"


def _is_wine_category(granular_category: str) -> bool:
    return granular_category in _WINE_CATEGORIES


def _is_beer_blik(granular_category: str, display_name: str) -> bool:
    if granular_category not in _BEER_CATEGORIES:
        return False
    name_lower = display_name.lower()
    return "blik" in name_lower or "can" in name_lower


# ---------------------------------------------------------------------------
# Validation — compare Gemini pack size against size tokens in display_name
# ---------------------------------------------------------------------------

_SIZE_TOKEN_RE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(kg|g|ml|cl|l|stuk|stuks|rol|rollen)\b",
    re.IGNORECASE,
)


def validate_pack_size(
    display_name: str,
    pack_size_value: Optional[float],
    pack_size_unit: Optional[str],
) -> Optional[str]:
    """Return a warning string if display_name's first size token disagrees with Gemini's
    pack_size_value/unit (within 5%), else None.

    We only check the unit-bearing value, not `pack_count` — multi-pack ordering in the
    display_name ('6 x 25 cl') is ambiguous to parse, so we'd rather be permissive than
    noisy. The goal here is catching gross errors like '500 g' → Gemini said 50.
    """
    if pack_size_value is None or not pack_size_unit:
        return None
    if pack_size_value <= 0:
        return None

    match = _find_first_size_token(display_name)
    if match is None:
        return None

    token_value, token_unit = match

    gemini_canonical = _UNIT_CONVERSION.get(pack_size_unit.strip().lower())
    token_canonical = _UNIT_CONVERSION.get(token_unit.strip().lower())
    if gemini_canonical is None or token_canonical is None:
        return None

    # Only compare if both canonicalise to the same base unit.
    if gemini_canonical[0] != token_canonical[0]:
        return (
            f"pack_size_unit='{pack_size_unit}' but display_name contains "
            f"'{token_value}{token_unit}' (different base unit)"
        )

    gemini_canon_value = pack_size_value * gemini_canonical[1]
    token_canon_value = token_value * token_canonical[1]
    if token_canon_value <= 0:
        return None

    ratio = gemini_canon_value / token_canon_value
    if ratio < 0.95 or ratio > 1.05:
        return (
            f"pack_size mismatch: Gemini={pack_size_value}{pack_size_unit} "
            f"vs display_name='{token_value}{token_unit}' (ratio={ratio:.2f})"
        )
    return None


def _find_first_size_token(display_name: str) -> Optional[tuple[float, str]]:
    match = _SIZE_TOKEN_RE.search(display_name)
    if match is None:
        return None
    raw_value = match.group(1).replace(",", ".")
    try:
        value = float(raw_value)
    except ValueError:
        return None
    unit = match.group(2).lower()
    # Normalise plurals.
    if unit == "stuks":
        unit = "stuk"
    elif unit == "rollen":
        unit = "rol"
    return value, unit


# ---------------------------------------------------------------------------
# Correctness gate — used by the API response serializer
# ---------------------------------------------------------------------------

def is_displayable(
    unit_price_value: Optional[float],
    unit_price_unit: Optional[str],
    quality: Optional[str],
    display_name: str,
    pack_size_value: Optional[float],
    pack_size_unit: Optional[str],
) -> bool:
    """Gate deciding whether unit-price fields may surface to API clients.

    Prefer null over wrong: on any doubt we return False so the iOS app hides the field.
    """
    if unit_price_value is None or unit_price_unit is None:
        return False
    if quality not in ("high", "medium"):
        return False
    if not (_MIN_UNIT_PRICE <= unit_price_value <= _MAX_UNIT_PRICE):
        return False
    if unit_price_unit not in CANONICAL_UNITS:
        return False
    if validate_pack_size(display_name, pack_size_value, pack_size_unit) is not None:
        return False
    return True


# ---------------------------------------------------------------------------
# Backfill helper — parse legacy formatted strings into numeric values
# ---------------------------------------------------------------------------

_LEGACY_DISPLAY_RE = re.compile(
    r"^€\s*(\d+(?:[.,]\d+)?)\s*/\s*(L|kg|stuk|rol)\s*$",
    re.IGNORECASE,
)


def parse_legacy_display_unit_price(text: Optional[str]) -> Optional[tuple[float, str]]:
    """Parse legacy '€0.84/L' → (0.84, 'l'). Returns None when unparseable."""
    if not text:
        return None
    match = _LEGACY_DISPLAY_RE.match(text.strip())
    if match is None:
        return None
    raw_value = match.group(1).replace(",", ".")
    try:
        value = float(raw_value)
    except ValueError:
        return None
    unit = match.group(2).lower()
    if unit not in CANONICAL_UNITS:
        return None
    return value, unit
