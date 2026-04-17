"""Shared promo scoring helpers used by the similarity ranker.

Kept here (not in services/) so any future consumer can call these without
pulling service-level async/DB plumbing.
"""
from typing import Optional

from app.models.enums import LoyaltyStatus


def brand_affinity_bonus(
    promo_normalized_brand: Optional[str],
    category_profile: Optional[dict],
) -> float:
    """Return 0.0-1.0 bonus for how well the promo's brand matches the user
    in the given category. No coupling to any scoring pipeline — call with
    whatever slice of user profile is available.

    Signals used (all optional on the profile):
      - preferred_brand (str) + loyalty_status (str)
      - brand_tally (dict[str, int])
    """
    if not promo_normalized_brand:
        return 0.0
    if not category_profile:
        return 0.0

    brand = promo_normalized_brand.lower()
    loyalty = category_profile.get("loyalty_status", "")
    preferred = (category_profile.get("preferred_brand") or "").lower()
    tally = category_profile.get("brand_tally") or {}

    if preferred and brand == preferred:
        if loyalty == LoyaltyStatus.STRICTLY_LOYAL.value:
            return 1.0
        if loyalty == LoyaltyStatus.SOFT_LOYAL.value:
            return 0.6
        return 0.4

    if any(brand == b.lower() for b in tally.keys()):
        return 0.3

    return 0.0
