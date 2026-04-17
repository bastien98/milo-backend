"""Tier-based similarity ranker for "similar promos" carousel.

Given a source promo, return only the most relevant other promos from
across all retailers. Quality over quantity — we'd rather return 5
genuinely similar promos than pad to 10 with weak matches.

Tiers (highest first):
  1  same_brand AND same_category                 — strongest match
  2  same_brand AND same_parent_category          — same brand, related family
  3  same_category AND name_sim >= 0.35           — close text twin, different brand
  4  same_category (any brand)                    — same category fallback

Deliberately NOT surfaced:
  - same brand with unrelated category (private labels span everything)
  - "affinity" / complementary categories (that's cross-sell, not similarity)
  - pure name-similarity across different categories (too noisy)

Within tier: cross-store bonus + promo_depth + price similarity +
urgency + personalization (0–1 weighted sum).

Store diversity: ≤3 items per retailer in output. If fewer than `limit`
strong matches exist, return fewer — do not pad.
"""
import logging
import math
from dataclasses import dataclass
from datetime import date
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.categories import get_parent_category
from app.core.promo_affinities import CATEGORY_AFFINITIES
from app.core.promo_scoring import brand_affinity_bonus
from app.db.repositories.promo_item_repo import PromoItemRepository

logger = logging.getLogger(__name__)

# Brand sentinel values used by the ingestion pipeline when no brand could
# be confidently extracted. These must NEVER match each other — otherwise
# two products with unknown brand would falsely rank as T1/T2.
_BRAND_SENTINELS = frozenset({"unknown", "none", "n/a", ""})


def _normalize_brand(brand: Optional[str]) -> Optional[str]:
    if not brand:
        return None
    b = brand.strip().lower()
    if b in _BRAND_SENTINELS:
        return None
    return b


NAME_SIM_TIER3 = 0.35

W_CROSS_STORE = 0.35
W_DISCOUNT = 0.25
W_PRICE_SIM = 0.15
W_URGENCY = 0.10
W_PERSONALIZATION = 0.15

MAX_ITEMS_PER_STORE = 3


@dataclass(frozen=True)
class _Ranked:
    tier: int
    score: float
    row: dict[str, Any]


class PromoNotFoundError(Exception):
    def __init__(self, promo_id: str):
        self.promo_id = promo_id
        super().__init__(f"Promo not found: {promo_id}")


class PromoSimilarityService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = PromoItemRepository(db)

    async def find_similar(
        self,
        source_id: str,
        limit: int = 10,
        category_profiles: Optional[dict] = None,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """Return (source_item_dict, ranked_similar_items).

        `category_profiles` is the full UserEnrichedProfile.category_profiles
        JSONB map (keyed by granular_category). The service picks the slice
        for the source promo's category internally.
        """
        source = await self.repo.get_by_id(source_id)
        if source is None:
            raise PromoNotFoundError(source_id)

        today = date.today()
        affinity_cats = CATEGORY_AFFINITIES.get(source.granular_category, [])
        category_profile = (
            category_profiles.get(source.granular_category)
            if category_profiles else None
        )
        source_parent = get_parent_category(source.granular_category)

        source_brand = _normalize_brand(source.normalized_brand)

        candidates = await self.repo.get_similar_candidates(
            source_id=source.id,
            source_brand=source_brand,
            source_category=source.granular_category,
            source_retailer=source.source_retailer,
            source_display_name=source.display_name,
            source_promo_price=source.promo_price,
            affinity_categories=affinity_cats,
            today=today,
        )

        # Post-fetch:
        #  - compute parent-category match (used by tier 2)
        #  - recompute is_same_brand in Python so sentinel brands on the
        #    candidate side ('unknown', '') also fail the brand check,
        #    not just NULLs
        for row in candidates:
            cat = str(row.get("granular_category") or "")
            row["is_same_parent_category"] = (
                get_parent_category(cat) == source_parent
            )
            cand_brand = _normalize_brand(row.get("normalized_brand"))
            row["is_same_brand"] = (
                source_brand is not None
                and cand_brand is not None
                and cand_brand == source_brand
            )

        ranked = self._rank(
            candidates=candidates,
            source_promo_price=source.promo_price,
            today=today,
            category_profile=category_profile,
        )

        slotted = self._slot_with_diversity(ranked, limit=limit)

        # Intentionally no fallback padding — quality over quantity. If only
        # N<limit strong matches exist, return N. The iOS carousel hides the
        # section when empty and shrinks when short.
        return (
            self._project_source(source),
            [self._project(r.row) for r in slotted],
        )

    def _rank(
        self,
        candidates: list[dict[str, Any]],
        source_promo_price: float,
        today: date,
        category_profile: Optional[dict],
    ) -> list[_Ranked]:
        out: list[_Ranked] = []
        for row in candidates:
            tier = self._tier(row)
            if tier is None:
                continue
            score = self._within_tier_score(
                row=row,
                source_promo_price=source_promo_price,
                today=today,
                category_profile=category_profile,
            )
            out.append(_Ranked(tier=tier, score=score, row=row))
        out.sort(key=lambda r: (r.tier, -r.score))
        return out

    @staticmethod
    def _tier(row: dict[str, Any]) -> Optional[int]:
        is_same_brand = bool(row.get("is_same_brand"))
        is_same_cat = bool(row.get("is_same_category"))
        is_same_parent_cat = bool(row.get("is_same_parent_category"))
        name_sim = float(row.get("name_sim") or 0.0)

        if is_same_brand and is_same_cat:
            return 1
        if is_same_brand and is_same_parent_cat:
            return 2
        if is_same_cat and name_sim >= NAME_SIM_TIER3:
            return 3
        if is_same_cat:
            return 4
        return None

    @staticmethod
    def _within_tier_score(
        row: dict[str, Any],
        source_promo_price: float,
        today: date,
        category_profile: Optional[dict],
    ) -> float:
        is_cross_store = 1.0 if row.get("is_cross_store") else 0.0

        promo_depth = float(row.get("promo_depth") or 0.0)
        discount = min(promo_depth / 50.0, 1.0)

        price_sim = 0.0
        promo_price = float(row.get("promo_price") or 0.0)
        if promo_price > 0 and source_promo_price > 0:
            price_sim = max(
                0.0,
                1.0 - abs(math.log(promo_price) - math.log(source_promo_price)),
            )

        validity_end = row.get("validity_end")
        urgency = 0.0
        if isinstance(validity_end, date):
            urgency = 1.0 if (validity_end - today).days <= 3 else 0.0

        personalization = brand_affinity_bonus(
            promo_normalized_brand=row.get("normalized_brand"),
            category_profile=category_profile,
        )

        return (
            W_CROSS_STORE * is_cross_store
            + W_DISCOUNT * discount
            + W_PRICE_SIM * price_sim
            + W_URGENCY * urgency
            + W_PERSONALIZATION * personalization
        )

    @staticmethod
    def _slot_with_diversity(
        ranked: list[_Ranked],
        limit: int,
        cap_per_store: int = MAX_ITEMS_PER_STORE,
    ) -> list[_Ranked]:
        out: list[_Ranked] = []
        per_store: dict[str, int] = {}
        for item in ranked:
            store = str(item.row.get("source_retailer") or "")
            if per_store.get(store, 0) >= cap_per_store:
                continue
            out.append(item)
            per_store[store] = per_store.get(store, 0) + 1
            if len(out) >= limit:
                break
        return out

    @staticmethod
    def _project_source(source) -> dict[str, Any]:
        return {
            "id": source.id,
            "display_name": source.display_name,
            "display_brand": source.display_brand,
            "normalized_brand": source.normalized_brand,
            "granular_category": source.granular_category,
            "source_retailer": source.source_retailer,
        }

    @staticmethod
    def _project(row: dict[str, Any]) -> dict[str, Any]:
        promo_depth = float(row.get("promo_depth") or 0.0)
        discount_pct = int(round(promo_depth))
        validity_start = row.get("validity_start")
        validity_end = row.get("validity_end")
        return {
            "item_key": row["id"],
            "brand": row.get("display_brand") or "",
            "product_name": row.get("display_name") or "",
            "original_price": float(row.get("original_price") or 0.0),
            "promo_price": float(row.get("promo_price") or 0.0),
            "savings": float(row.get("savings_amount") or 0.0),
            "savings_amount": float(row.get("savings_amount") or 0.0),
            "min_purchase_qty": int(row.get("min_purchase_qty") or 1),
            "effective_unit_price": None,
            "discount_percentage": discount_pct,
            "mechanism": row.get("display_mechanism") or "",
            "validity_start": validity_start.isoformat() if isinstance(validity_start, date) else (validity_start or ""),
            "validity_end": validity_end.isoformat() if isinstance(validity_end, date) else (validity_end or ""),
            "promo_folder_url": row.get("promo_folder_url"),
            "page_number": row.get("page_number"),
            "display_name": row.get("display_name"),
            "display_mechanism": row.get("display_mechanism"),
            "display_description": row.get("display_description") or "",
            "display_unit_price": row.get("display_unit_price"),
            "display_savings_label": row.get("display_savings_label") or "",
            "bucket": None,
            "bucket_label": None,
            "thumbnail_url": row.get("thumbnail_url"),
            "image_url": row.get("image_url"),
            "store_name": row.get("source_retailer"),
        }
