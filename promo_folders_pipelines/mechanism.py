"""
Deterministic promo-mechanism logic.

Gemini extracts the perceptual signal — `mechanism_kind` + `mechanism_x` + `mechanism_y`
— and this module derives every string and number the app needs from that signal:
canonical display labels, Dutch descriptions, user-facing savings labels, minimum
purchase quantity, savings amount, and reverse-inferred original price.

Pure functions, no I/O. All cross-store normalization lives here.
"""

from __future__ import annotations

from typing import Literal, Optional

MechanismKind = Literal[
    "buy_x_get_y_free",
    "second_half_price",
    "second_percent_off",
    "percent_off",
    "percent_off_from_n",
    "euro_off",
    "n_for_euro",
    "price_reduction",
]

ALL_KINDS: tuple[MechanismKind, ...] = (
    "buy_x_get_y_free",
    "second_half_price",
    "second_percent_off",
    "percent_off",
    "percent_off_from_n",
    "euro_off",
    "n_for_euro",
    "price_reduction",
)


def _int_or_none(v: Optional[float]) -> Optional[int]:
    if v is None:
        return None
    return int(round(v))


def _fmt_euro(v: float) -> str:
    return f"€{v:.2f}"


def _fmt_pct(v: float) -> str:
    # Integer percent when possible ("-25%"), else one decimal ("-12.5%").
    iv = int(round(v))
    if abs(v - iv) < 0.05:
        return f"{iv}%"
    return f"{v:.1f}%"


def canonical_label(kind: MechanismKind, x: Optional[float], y: Optional[float]) -> str:
    """Normalized Dutch display label for the mechanism pill."""
    if kind == "buy_x_get_y_free":
        ix, iy = _int_or_none(x), _int_or_none(y)
        if ix is None or iy is None:
            return "Gratis Deal"
        return f"{ix}+{iy} Gratis"

    if kind == "second_half_price":
        return "2e aan Halve Prijs"

    if kind == "second_percent_off":
        if x is None:
            return "2e aan -50%"
        return f"2e aan -{_fmt_pct(x)}"

    if kind == "percent_off":
        if x is None:
            return "Korting"
        return f"-{_fmt_pct(x)}"

    if kind == "percent_off_from_n":
        if x is None or y is None:
            return "Korting Vanaf Meerdere"
        iy = _int_or_none(y) or 2
        return f"-{_fmt_pct(x)} Vanaf {iy} Verpakkingen"

    if kind == "euro_off":
        if x is None:
            return "Korting"
        return f"{_fmt_euro(x)} Korting"

    if kind == "n_for_euro":
        if x is None or y is None:
            return "Multi-pack Deal"
        ix = _int_or_none(x) or 1
        return f"{ix} Voor {_fmt_euro(y)}"

    if kind == "price_reduction":
        return "Prijsverlaging"

    return "Promo"


def min_purchase_qty(kind: MechanismKind, x: Optional[float], y: Optional[float]) -> int:
    """Minimum number of items/packs a shopper must buy to complete the deal."""
    if kind == "buy_x_get_y_free":
        ix, iy = _int_or_none(x), _int_or_none(y)
        if ix is None or iy is None:
            return 1
        return max(1, ix + iy)

    if kind in ("second_half_price", "second_percent_off"):
        return 2

    if kind == "percent_off_from_n":
        iy = _int_or_none(y)
        return max(1, iy) if iy else 1

    if kind == "n_for_euro":
        ix = _int_or_none(x)
        return max(1, ix) if ix else 1

    # percent_off, euro_off, price_reduction — single-item mechanics
    return 1


def compute_savings(
    kind: MechanismKind,
    x: Optional[float],
    y: Optional[float],
    original_price: Optional[float],
    promo_price: Optional[float],
    stated_savings: Optional[float],
) -> Optional[float]:
    """Total euro savings when the shopper completes the deal.

    `stated_savings` wins when explicitly printed on the page.
    """
    if stated_savings is not None and stated_savings > 0:
        return round(stated_savings, 2)

    op = original_price
    pp = promo_price

    if kind == "buy_x_get_y_free":
        iy = _int_or_none(y)
        if iy is None or op is None:
            return None
        return round(iy * op, 2)

    if kind == "second_half_price":
        if op is None:
            return None
        return round(op / 2, 2)

    if kind == "second_percent_off":
        if op is None or x is None:
            return None
        return round(op * x / 100, 2)

    if kind == "percent_off":
        if x is None:
            return None
        base = op if op is not None else pp
        if base is None:
            return None
        return round(base * x / 100, 2)

    if kind == "percent_off_from_n":
        if op is None or x is None or y is None:
            return None
        iy = _int_or_none(y) or 1
        return round(op * iy * x / 100, 2)

    if kind == "euro_off":
        if x is None:
            return None
        return round(x, 2)

    if kind == "n_for_euro":
        ix = _int_or_none(x)
        if ix is None or op is None or y is None:
            return None
        saved = ix * op - y
        return round(saved, 2) if saved > 0 else None

    if kind == "price_reduction":
        if op is None or pp is None:
            return None
        saved = op - pp
        return round(saved, 2) if saved > 0 else None

    return None


def infer_original_price(
    kind: MechanismKind,
    x: Optional[float],
    y: Optional[float],
    promo_price: Optional[float],
    stated_savings: Optional[float],
) -> Optional[float]:
    """Reverse-compute original_price when only promo_price is visible."""
    if promo_price is None:
        return None

    if kind == "buy_x_get_y_free":
        # Shelf price per pack is the same before and after the promo.
        return promo_price

    if kind == "percent_off":
        if x is None or x <= 0 or x >= 100:
            return None
        return round(promo_price / (1 - x / 100), 2)

    if kind == "second_half_price":
        # promo_price shown is the regular shelf price.
        return promo_price

    if kind == "second_percent_off":
        # Same — promo_price shown is the regular shelf price.
        return promo_price

    if kind == "percent_off_from_n":
        # Same — promo_price on the shelf is the regular shelf price; discount applies at checkout.
        return promo_price

    if kind == "n_for_euro":
        # promo_price shown is typically the multi-pack shelf price (unit).
        return promo_price

    if kind == "euro_off":
        if stated_savings is not None:
            return round(promo_price + stated_savings, 2)
        if x is not None:
            return round(promo_price + x, 2)
        return None

    return None


def infer_promo_price(
    kind: MechanismKind,
    x: Optional[float],
    y: Optional[float],
    original_price: Optional[float],
) -> Optional[float]:
    """Reverse-compute promo_price when only original_price is visible."""
    if original_price is None:
        return None

    if kind == "buy_x_get_y_free":
        return original_price

    if kind == "percent_off":
        if x is None:
            return None
        return round(original_price * (1 - x / 100), 2)

    if kind == "n_for_euro":
        ix = _int_or_none(x)
        if ix is None or ix <= 0 or y is None:
            return None
        return round(y / ix, 2)

    if kind == "euro_off":
        if x is None:
            return None
        return round(max(0.0, original_price - x), 2)

    if kind in ("second_half_price", "second_percent_off", "percent_off_from_n", "price_reduction"):
        # Shelf price unchanged; the discount is applied at checkout.
        return original_price

    return None


def display_description(kind: MechanismKind, x: Optional[float], y: Optional[float]) -> str:
    """Plain-language Dutch explanation of the deal (~80 chars max)."""
    if kind == "buy_x_get_y_free":
        ix, iy = _int_or_none(x), _int_or_none(y)
        if ix is None or iy is None:
            return "Koop meer, krijg gratis."
        if ix == 1 and iy == 1:
            return "Koop er 1, krijg er 1 gratis."
        return f"Koop er {ix}, krijg er {iy} gratis."

    if kind == "second_half_price":
        return "Tweede stuk aan halve prijs."

    if kind == "second_percent_off":
        if x is None:
            return "Korting op het tweede stuk."
        return f"Tweede stuk aan -{_fmt_pct(x)}."

    if kind == "percent_off":
        if x is None:
            return "Korting op dit product."
        return f"-{_fmt_pct(x)} korting."

    if kind == "percent_off_from_n":
        if x is None or y is None:
            return "Korting bij meerdere verpakkingen."
        iy = _int_or_none(y) or 2
        return f"Vanaf {iy} verpakkingen: -{_fmt_pct(x)} korting."

    if kind == "euro_off":
        if x is None:
            return "Korting op dit product."
        return f"{_fmt_euro(x)} korting per stuk."

    if kind == "n_for_euro":
        ix = _int_or_none(x)
        if ix is None or y is None:
            return "Multi-pack aanbieding."
        return f"{ix} voor {_fmt_euro(y)}."

    if kind == "price_reduction":
        return "Tijdelijk goedkoper."

    return "Promotie."


def display_savings_label(
    kind: MechanismKind,
    x: Optional[float],
    y: Optional[float],
    savings: Optional[float],
) -> str:
    """Human-friendly savings chip."""
    if kind == "buy_x_get_y_free":
        iy = _int_or_none(y)
        if iy is None:
            return "Gratis Item"
        if iy == 1:
            return "1 Gratis Item"
        return f"{iy} Gratis Items"

    if kind == "second_half_price":
        return "2e aan Halve Prijs"

    if kind == "second_percent_off":
        if x is None:
            return "Korting 2e Stuk"
        return f"2e aan -{_fmt_pct(x)}"

    if kind in ("percent_off", "percent_off_from_n"):
        if x is None:
            return "Korting"
        return f"Tot -{_fmt_pct(x)} Korting"

    # euro_off, n_for_euro, price_reduction — fall back to the numeric savings if known.
    if savings is not None and savings > 0:
        return f"Bespaar {_fmt_euro(savings)}"

    if kind == "euro_off" and x is not None:
        return f"{_fmt_euro(x)} Korting"

    return "Promo"
