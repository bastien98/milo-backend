"""Compute effective per-item promo depth from pricing fields."""


def compute_promo_depth(
    savings_amount: float,
    original_price: float,
    min_purchase_qty: int,
) -> float:
    """Return the effective per-item discount percentage (0.0–100.0).

    Formula: savings_amount / (min_purchase_qty * original_price) * 100
    """
    if original_price <= 0 or min_purchase_qty < 1:
        return 0.0

    depth = (savings_amount / (min_purchase_qty * original_price)) * 100
    return round(max(0.0, min(depth, 100.0)), 1)
