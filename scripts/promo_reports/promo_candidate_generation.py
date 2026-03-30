"""Promo-first reverse matching engine.

Instead of searching promos FOR users, promos find their matching users:
1. Fetch all active promos from promo_items table
2. Fetch all users with category_profiles
3. For each promo, score against matching users' category profiles
4. Assign to UX buckets (staples / stock_up / ending_soon / discover)
5. Store pre-computed feed in promo_candidates table
"""

import hashlib
import logging
from datetime import date, timedelta
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.categories import get_parent_category
from app.core.promo_affinities import CATEGORY_AFFINITIES
from app.core.promo_reports import current_brussels_date as shared_current_brussels_date
from app.db.repositories.enriched_profile_repo import EnrichedProfileRepository
from app.db.repositories.promo_item_repo import PromoItemRepository
from app.models.enums import LoyaltyStatus, PromoBucket
from app.models.promo_item import PromoItem

logger = logging.getLogger(__name__)

# Scoring weights — certainty-weighted (brand > discount > frequency > urgency)
W_FREQUENCY = 0.20
W_DISCOUNT = 0.30
W_URGENCY = 0.05
W_BRAND = 0.45

# Bucket sizes per store (total = 15)
BUCKET_SIZES = {
    PromoBucket.STAPLES: 5,
    PromoBucket.STOCK_UP: 4,
    PromoBucket.ENDING_SOON: 3,
    PromoBucket.DISCOVER: 3,
}

# "Ending Soon" window in days
ENDING_SOON_DAYS = 2

# Per-bucket minimum score — promos below these thresholds are dropped (quality > quantity)
BUCKET_MIN_SCORES = {
    PromoBucket.STAPLES: 0.4,
    PromoBucket.STOCK_UP: 0.3,
    PromoBucket.ENDING_SOON: 0.3,
    PromoBucket.DISCOVER: 0.15,
}

BUCKET_LABELS = {
    PromoBucket.STAPLES: "Your Everyday Staples",
    PromoBucket.STOCK_UP: "Stock Up & Save",
    PromoBucket.ENDING_SOON: "Ending Soon",
    PromoBucket.DISCOVER: "Discover for You",
}


class PromoCandidateGenerationService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.enriched_repo = EnrichedProfileRepository(db)
        self.promo_repo = PromoItemRepository(db)

    async def build_candidates(
        self,
        user_id: str,
        report_date: Optional[date] = None,
    ) -> Optional[dict]:
        """Build a candidate pool for a user using promo-first reverse matching.

        Returns a dict with:
          - candidates: list of candidate item dicts (all stores, bucketed)
          - interest_item_count: number of category profiles
          - total_matches: total candidate count
        """
        report_date = report_date or _current_brussels_date()

        # Fetch user's category profiles
        profile = await self.enriched_repo.get_by_user_id(user_id)
        if not profile or not profile.category_profiles:
            return None

        category_profiles: dict[str, dict] = profile.category_profiles

        # Fetch all active promos
        active_promos = await self.promo_repo.get_active(report_date)
        if not active_promos:
            return None

        # Score each promo against user's profiles
        scored_promos = _score_promos_for_user(active_promos, category_profiles, report_date)
        if not scored_promos:
            return None

        # Assign to buckets per store
        candidates = _assign_buckets(scored_promos, category_profiles, report_date)
        if not candidates:
            return None

        return {
            "candidates": candidates,
            "interest_item_count": len(category_profiles),
            "total_matches": len(candidates),
        }


class ProfileNotFoundError(Exception):
    def __init__(self, user_id: str):
        self.user_id = user_id
        super().__init__(f"No enriched profile found for user {user_id}")


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _score_promos_for_user(
    promos: list[PromoItem],
    category_profiles: dict[str, dict],
    report_date: date,
) -> list[dict]:
    """Score each promo item against the user's category profiles.

    Returns a flat list of scored promo dicts.
    """
    # Build a set of all categories the user has purchased
    user_categories = set(category_profiles.keys())

    # Build affinity target set: categories reachable via affinity dict
    affinity_targets: dict[str, str] = {}  # target_cat -> source_cat
    for src_cat in user_categories:
        for target_cat in CATEGORY_AFFINITIES.get(src_cat, []):
            if target_cat not in user_categories and target_cat not in affinity_targets:
                affinity_targets[target_cat] = src_cat

    scored = []

    for promo in promos:
        cat = promo.granular_category
        if cat in ("Other", "Discount"):
            continue

        cat_profile = category_profiles.get(cat)
        is_affinity = cat in affinity_targets
        source_cat = affinity_targets.get(cat)

        if not cat_profile and not is_affinity:
            continue

        # Calculate score components
        if cat_profile:
            score, match_type = _compute_score(promo, cat_profile)
        else:
            # Affinity match — use the source category's profile for frequency
            # but give a lower base score
            source_profile = category_profiles.get(source_cat, {}) if source_cat else {}
            score = _compute_affinity_score(promo, source_profile)
            match_type = "affinity"

        promo_dict = _promo_to_dict(promo, score, match_type, cat_profile, report_date)
        scored.append(promo_dict)

    return scored


def _compute_score(promo: PromoItem, cat_profile: dict) -> tuple[float, str]:
    """Compute the recommendation score for a promo-category pair."""
    avg_days = cat_profile.get("average_days_between")
    frequency = min(14.0 / max(avg_days, 1), 1.0) if avg_days and avg_days > 0 else 0.0

    discount_depth = (promo.promo_depth / 100.0) if promo.promo_depth else 0.0
    discount_depth = min(discount_depth, 1.0)

    restock = cat_profile.get("restock_urgency")
    urgency = min(restock, 1.0) if restock and restock > 0 else 0.0

    brand_bonus = _compute_brand_bonus(promo, cat_profile)

    score = (
        W_FREQUENCY * frequency
        + W_DISCOUNT * discount_depth
        + W_URGENCY * urgency
        + W_BRAND * brand_bonus
    )

    # Determine match type for bucket assignment
    loyalty = cat_profile.get("loyalty_status", "")
    if loyalty in (LoyaltyStatus.STRICTLY_LOYAL.value, LoyaltyStatus.SOFT_LOYAL.value):
        match_type = "loyal"
    else:
        match_type = "agnostic"

    return round(score, 4), match_type


def _compute_brand_bonus(promo: PromoItem, cat_profile: dict) -> float:
    """Compute brand affinity bonus (0.0 to 1.0) using exact brand matching."""
    promo_brand = (promo.normalized_brand or "").lower()
    if not promo_brand:
        return 0.0

    loyalty = cat_profile.get("loyalty_status", "")
    preferred_brand = cat_profile.get("preferred_brand", "")
    brand_tally = cat_profile.get("brand_tally", {})

    # Exact match on preferred brand
    if preferred_brand and promo_brand == preferred_brand.lower():
        if loyalty == LoyaltyStatus.STRICTLY_LOYAL.value:
            return 1.0
        elif loyalty == LoyaltyStatus.SOFT_LOYAL.value:
            return 0.5

    # Check if user has purchased this exact brand
    if promo_brand in {b.lower() for b in brand_tally}:
        return 0.3

    return 0.0


def _compute_affinity_score(promo: PromoItem, source_profile: dict) -> float:
    """Compute a lower score for affinity/discovery matches."""
    discount_depth = (promo.promo_depth / 100.0) if promo.promo_depth else 0.0
    discount_depth = min(discount_depth, 1.0)

    # Affinity items get a base score weighted toward discount depth
    return round(0.1 + 0.3 * discount_depth, 4)


# ---------------------------------------------------------------------------
# Bucket assignment
# ---------------------------------------------------------------------------

def _assign_buckets(
    scored_promos: list[dict],
    category_profiles: dict[str, dict],
    report_date: date,
) -> list[dict]:
    """Assign scored promos to UX buckets per store, capped at 15 per store."""
    # Group by store
    by_store: dict[str, list[dict]] = {}
    for p in scored_promos:
        store = p.get("store_name", "")
        if store not in by_store:
            by_store[store] = []
        by_store[store].append(p)

    ending_soon_cutoff = report_date + timedelta(days=ENDING_SOON_DAYS)
    all_candidates = []

    for store, promos in by_store.items():
        # Sort all promos by score descending
        promos.sort(key=lambda x: x.get("score", 0), reverse=True)

        # Tag each promo with ending-soon flag and match_type
        seen_keys: set[str] = set()
        ending_soon_candidates = []
        staple_candidates = []
        stock_up_candidates = []
        discover_candidates = []

        for p in promos:
            key = p.get("item_key", "")
            if key in seen_keys:
                continue

            match_type = p.get("match_type", "")
            validity_end_str = p.get("validity_end", "")

            # Check if ending soon
            is_ending_soon = False
            if validity_end_str:
                try:
                    v_end = date.fromisoformat(str(validity_end_str))
                    is_ending_soon = v_end <= ending_soon_cutoff
                except (ValueError, TypeError):
                    pass

            if match_type == "affinity":
                discover_candidates.append(p)
            elif is_ending_soon:
                ending_soon_candidates.append(p)
            elif match_type == "loyal":
                staple_candidates.append(p)
            else:
                stock_up_candidates.append(p)

        # Fill buckets with quality gate — no cascade overflow, empty buckets are OK
        store_candidates = []

        for bucket, candidates, max_items in [
            (PromoBucket.STAPLES, staple_candidates, BUCKET_SIZES[PromoBucket.STAPLES]),
            (PromoBucket.STOCK_UP, stock_up_candidates, BUCKET_SIZES[PromoBucket.STOCK_UP]),
            (PromoBucket.ENDING_SOON, ending_soon_candidates, BUCKET_SIZES[PromoBucket.ENDING_SOON]),
            (PromoBucket.DISCOVER, discover_candidates, BUCKET_SIZES[PromoBucket.DISCOVER]),
        ]:
            min_score = BUCKET_MIN_SCORES[bucket]
            qualified = [c for c in candidates if c.get("score", 0) >= min_score]
            for c in qualified[:max_items]:
                key = c.get("item_key", "")
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                c["bucket"] = bucket.value
                c["bucket_label"] = BUCKET_LABELS[bucket]
                store_candidates.append(c)

        all_candidates.extend(store_candidates)

    return all_candidates


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _promo_to_dict(
    promo: PromoItem,
    score: float,
    match_type: str,
    cat_profile: Optional[dict],
    report_date: date,
) -> dict:
    """Convert a PromoItem ORM object to a candidate dict."""
    original_price = promo.original_price or 0
    promo_price = promo.promo_price or 0
    savings_amount = promo.savings_amount or 0
    min_purchase_qty = promo.min_purchase_qty or 1
    discount_pct = round((savings_amount / original_price) * 100) if original_price > 0 else 0

    # For multi-buy deals (e.g. 2+2 gratis), compute effective per-unit cost
    if min_purchase_qty >= 1 and original_price > 0:
        effective_unit_price = round(
            (original_price * min_purchase_qty - savings_amount) / min_purchase_qty, 2
        )
    else:
        effective_unit_price = promo_price

    item_key = _build_item_key(promo)

    return {
        "item_key": item_key,
        "score": score,
        "match_type": match_type,
        # Brand
        "brand": promo.display_brand or "",
        "normalized_brand": promo.normalized_brand or "",
        # Display fields
        "display_name": promo.display_name,
        "display_mechanism": promo.display_mechanism,
        "display_description": promo.display_description,
        "display_unit_price": promo.display_unit_price,
        "display_savings_label": promo.display_savings_label,
        # Pricing
        "original_price": original_price,
        "promo_price": promo_price,
        "savings_amount": savings_amount,
        "discount_percentage": discount_pct,
        "promo_depth": promo.promo_depth,
        "min_purchase_qty": min_purchase_qty,
        "effective_unit_price": effective_unit_price,
        # Category & source
        "granular_category": promo.granular_category,
        "store_name": promo.source_retailer,
        "promo_folder_url": promo.promo_folder_url,
        "page_number": promo.page_number,
        # Validity
        "validity_start": promo.validity_start.isoformat() if promo.validity_start else "",
        "validity_end": promo.validity_end.isoformat() if promo.validity_end else "",
        # User context (from category profile)
        "restock_urgency": cat_profile.get("restock_urgency") if cat_profile else None,
        "purchase_frequency_days": cat_profile.get("average_days_between") if cat_profile else None,
        "avg_price_paid": cat_profile.get("avg_price_paid") if cat_profile else None,
    }


def _build_item_key(promo: PromoItem) -> str:
    """Generate a deterministic key for deduplication."""
    raw = "|".join([
        (promo.display_name or "").strip().lower(),
        (promo.source_retailer or "").strip().lower(),
        (promo.display_mechanism or "").strip().lower(),
        f"{promo.original_price:.2f}",
        f"{promo.promo_price:.2f}",
        str(promo.validity_start or ""),
        str(promo.validity_end or ""),
    ])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _current_brussels_date() -> date:
    return shared_current_brussels_date()
