"""Offline promo candidate generation service.

Retrieves the user's enriched profile, searches Pinecone for matching
promotions, and reranks for relevance.
"""

import asyncio
import hashlib
import logging
import time
from datetime import date
from typing import Any, Optional

from pinecone import Pinecone
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.promo_reports import (
    compute_promo_week as shared_compute_promo_week,
    current_brussels_date as shared_current_brussels_date,
)
from app.config import get_settings
from app.db.repositories.enriched_profile_repo import EnrichedProfileRepository

logger = logging.getLogger(__name__)

# Search tuning
SEARCH_TOP_K = 20
RERANK_TOP_N = 5
RERANK_SCORE_THRESHOLD = 0.55



class PromoCandidateGenerationService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.settings = get_settings()
        self.enriched_repo = EnrichedProfileRepository(db)
        self._pc = Pinecone(api_key=self.settings.PINECONE_API_KEY)
        self._pinecone_index = self._pc.Index(host=self.settings.PINECONE_INDEX_HOST)

    async def build_candidates(
        self,
        user_id: str,
        report_date: Optional[date] = None,
    ) -> Optional[dict]:
        """Build a weekly candidate pool: search all stores, rerank for relevance.

        Returns a dict with:
          - candidates: list of candidate item dicts (all stores)
          - interest_item_count: int
          - total_matches: int

        Returns None if the user has no interest items or no matches.
        """
        report_date = report_date or _current_brussels_date()
        report_date_epoch = _date_to_epoch(report_date.isoformat())

        profile = await self._fetch_enriched_profile(user_id)
        interest_items = profile.get("promo_interest_items", [])
        if not interest_items:
            return None

        promo_results = await self._search_all_promos(interest_items, report_date_epoch)

        if not any(promo_results.values()):
            return None

        candidates = _build_candidate_items(promo_results, interest_items)
        if not candidates:
            return None

        return {
            "candidates": candidates,
            "interest_item_count": len(interest_items),
            "total_matches": len(candidates),
        }

    async def _fetch_enriched_profile(self, user_id: str) -> dict:
        """Fetch the user's enriched profile from the database."""
        ep = await self.enriched_repo.get_by_user_id(user_id)
        if not ep:
            raise ProfileNotFoundError(user_id)

        shopping_habits = ep.shopping_habits or {}
        promo_interest_items = ep.promo_interest_items or []

        return {
            "shopping_habits": shopping_habits,
            "promo_interest_items": promo_interest_items,
            "data_period_start": str(ep.data_period_start) if ep.data_period_start else None,
            "data_period_end": str(ep.data_period_end) if ep.data_period_end else None,
            "receipts_analyzed": ep.receipts_analyzed,
        }

    async def _search_all_promos(
        self,
        interest_items: list[dict],
        report_date_epoch: int,
    ) -> dict[str, list[dict]]:
        """Search Pinecone for promotions matching each interest item."""
        sem = asyncio.Semaphore(5)

        async def _search_one(item: dict) -> tuple[str, list[dict]]:
            name = item["normalized_name"]
            async with sem:
                promos = await asyncio.to_thread(
                    _search_promos_for_item,
                    self._pc,
                    self._pinecone_index,
                    item,
                    report_date_epoch,
                )
            if promos:
                logger.info(
                    f"Promo search '{name}': {len(promos)} matches "
                    f"(scores: {[p['relevance_score'] for p in promos]})"
                )
            return name, promos

        results = await asyncio.gather(
            *[_search_one(item) for item in interest_items]
        )
        return dict(results)



# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class ProfileNotFoundError(Exception):
    def __init__(self, user_id: str):
        self.user_id = user_id
        super().__init__(f"No enriched profile found for user {user_id}")


# ---------------------------------------------------------------------------
# Pinecone helpers (synchronous — called via asyncio.to_thread)
# ---------------------------------------------------------------------------

def _search_promos_for_item(
    pc: Pinecone,
    index,
    item: dict,
    report_date_epoch: int,
) -> list[dict]:
    """Search Pinecone for promotions matching a single promo interest item.

    Two search modes:
    - Brand-loyal: query includes brand (via normalized_name) to find
      promos for the user's preferred brand.
    - Non-brand-loyal: query uses product_name_no_brand (brand stripped)
      to find the best deal across all brands.
    """
    normalized_name = item["normalized_name"]
    product_name_no_brand = item.get("product_name_no_brand")
    granular_category = item.get("granular_category")
    interest_category = item.get("interest_category")

    filter_dict = _build_active_filter(granular_category, report_date_epoch)
    fallback_filter = _build_active_filter(None, report_date_epoch)

    cat_suffix = ""
    if granular_category and granular_category != "Other":
        cat_suffix = f" [{granular_category}]"

    # Build query texts — two modes
    if interest_category == "brand_loyal":
        # Include brand — match specific brand's promos
        # normalized_name already contains brand (e.g., "jupiler pils")
        query_texts = [f"{normalized_name}{cat_suffix}"]
    else:
        # Exclude brand — match promos across all brands
        search_name = product_name_no_brand or normalized_name
        query_texts = [f"{search_name}{cat_suffix}"]

    # Search + rerank across all queries
    seen_ids: set[str] = set()
    all_results: list[dict] = []

    for query_text in query_texts:
        hits = _pinecone_search_and_rerank(index, query_text, filter_dict)

        # Fallback without category filter
        if not hits and granular_category:
            hits = _pinecone_search_and_rerank(index, query_text, filter_dict=fallback_filter)

        for hit in hits:
            hit_id = hit.get("_id", "")
            if hit_id and hit_id in seen_ids:
                continue
            if hit_id:
                seen_ids.add(hit_id)
            all_results.append(hit)

    # Filter by rerank score threshold
    relevant = []
    for hit in all_results:
        score = hit.get("_score", 0)
        if score >= RERANK_SCORE_THRESHOLD:
            promo = _build_promo_dict(hit.get("fields", {}), score)
            if _is_display_eligible_promo(promo, report_date_epoch):
                relevant.append(promo)

    # Brand relevance is now handled by semantic search — display_name
    # contains the brand, so the rerank score already reflects brand match.

    # Fallback: broader category search
    if not relevant and granular_category and interest_category != "category_fallback":
        category_term = granular_category.split(" & ")[0].lower()
        if category_term != normalized_name:
            fallback_hits = _pinecone_search_and_rerank(
                index, f"{category_term}{cat_suffix}", filter_dict
            )
            for hit in fallback_hits:
                score = hit.get("_score", 0)
                if score >= RERANK_SCORE_THRESHOLD:
                    promo = _build_promo_dict(hit.get("fields", {}), score)
                    if _is_display_eligible_promo(promo, report_date_epoch):
                        relevant.append(promo)
            relevant = relevant[:RERANK_TOP_N]

    return relevant[:RERANK_TOP_N]


def _pinecone_search_and_rerank(
    index, query_text: str, filter_dict: Optional[dict],
    _max_retries: int = 3,
) -> list[dict]:
    """Execute integrated search + rerank in a single Pinecone API call.

    Retries with exponential backoff on 429 rate-limit errors.
    """
    query: dict[str, Any] = {
        "inputs": {"text": query_text},
        "top_k": SEARCH_TOP_K,
    }
    if filter_dict:
        query["filter"] = filter_dict

    rerank = {
        "model": "bge-reranker-v2-m3",
        "rank_fields": ["text"],
        "top_n": RERANK_TOP_N,
    }

    for attempt in range(_max_retries):
        try:
            try:
                results = index.search_records(namespace="__default__", query=query, rerank=rerank)
            except (AttributeError, TypeError):
                results = index.search(namespace="__default__", query=query, rerank=rerank)
            return _extract_hits(results)
        except Exception as e:
            error_str = str(e)
            is_rate_limit = "429" in error_str or "Too Many Requests" in error_str or "RESOURCE_EXHAUSTED" in error_str
            if is_rate_limit and attempt < _max_retries - 1:
                wait = 2 ** attempt  # 1s, 2s, 4s
                logger.warning(f"Pinecone rerank rate-limited (attempt {attempt + 1}), retrying in {wait}s...")
                time.sleep(wait)
                continue
            logger.warning(f"Pinecone search+rerank failed: {e}")
            return []


def _build_active_filter(
    granular_category: Optional[str],
    report_date_epoch: int,
) -> dict:
    clauses: list[dict[str, Any]] = [
        {"validity_start_epoch": {"$lte": report_date_epoch}},
        {"validity_end_epoch": {"$gte": report_date_epoch}},
    ]
    if granular_category:
        clauses.append({"granular_category": {"$eq": granular_category}})
    return {"$and": clauses}


def _is_display_eligible_promo(promo: dict, report_date_epoch: int) -> bool:
    # All display fields must be present — no fallbacks
    display_name = (promo.get("display_name") or "").strip()
    display_mechanism = (promo.get("display_mechanism") or "").strip()
    retailer = (promo.get("source_retailer") or "").strip()
    if not display_name or not display_mechanism or not retailer:
        return False

    if not promo.get("validity_start") or not promo.get("validity_end"):
        return False

    try:
        validity_start_epoch = int(promo["validity_start_epoch"])
        validity_end_epoch = int(promo["validity_end_epoch"])
    except (KeyError, TypeError, ValueError):
        return False

    if validity_start_epoch > validity_end_epoch:
        return False
    if report_date_epoch < validity_start_epoch or report_date_epoch > validity_end_epoch:
        return False

    # Prices and savings are required
    original = _safe_price(promo.get("original_price"))
    promo_price = _safe_price(promo.get("promo_price"))
    savings = _safe_price(promo.get("savings_amount"))
    if original is None or promo_price is None or savings is None:
        return False
    if original <= 0 or promo_price <= 0 or savings <= 0:
        return False
    if promo_price > original:
        return False

    return True


def _safe_price(value) -> Optional[float]:
    """Return a float if value is a valid price, else None."""
    if value is None:
        return None
    try:
        v = float(value)
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


def _build_item_key(fields: dict) -> str:
    original_price = _coerce_price(fields.get("original_price"))
    promo_price = _coerce_price(fields.get("promo_price"))
    raw = "|".join(
        [
            (fields.get("display_name") or "").strip().lower(),
            (fields.get("source_retailer") or "").strip().lower(),
            (fields.get("display_mechanism") or "").strip().lower(),
            f"{original_price:.2f}",
            f"{promo_price:.2f}",
            str(fields.get("validity_start") or ""),
            str(fields.get("validity_end") or ""),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _build_promo_dict(fields: dict, score: float) -> dict:
    promo = {
        "relevance_score": round(score, 4),
        "item_key": _build_item_key(fields),
        # Display fields
        "display_name": fields.get("display_name", ""),
        "display_mechanism": fields.get("display_mechanism", ""),
        "display_description": fields.get("display_description", ""),
        "display_unit_price": fields.get("display_unit_price"),
        "display_savings_label": fields.get("display_savings_label", ""),
        # Pricing
        "original_price": fields.get("original_price"),
        "promo_price": fields.get("promo_price"),
        "savings_amount": fields.get("savings_amount"),
        # Category
        "granular_category": fields.get("granular_category", ""),
        "parent_category": fields.get("parent_category", ""),
        # Metadata
        "validity_start": fields.get("validity_start", ""),
        "validity_end": fields.get("validity_end", ""),
        "validity_start_epoch": fields.get("validity_start_epoch"),
        "validity_end_epoch": fields.get("validity_end_epoch"),
        "source_retailer": fields.get("source_retailer", ""),
        "promo_folder_url": fields.get("promo_folder_url"),
    }
    return promo


def _coerce_price(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0




def _extract_hits(results) -> list[dict]:
    if hasattr(results, "result"):
        result = results.result
        if hasattr(result, "hits"):
            return [_normalize_hit(h) for h in result.hits]

    if isinstance(results, dict):
        if "result" in results:
            return [_normalize_hit(h) for h in results["result"].get("hits", [])]
        if "matches" in results:
            return [_normalize_hit(m) for m in results["matches"]]

    if hasattr(results, "matches"):
        return [_normalize_hit(m) for m in results.matches]

    return []


def _normalize_hit(hit) -> dict:
    if isinstance(hit, dict):
        if "fields" not in hit and "metadata" in hit:
            hit["fields"] = hit["metadata"]
        return hit

    d = {
        "_id": getattr(hit, "_id", getattr(hit, "id", "")),
        "_score": getattr(hit, "_score", getattr(hit, "score", 0)),
    }
    if hasattr(hit, "fields"):
        d["fields"] = dict(hit.fields) if not isinstance(hit.fields, dict) else hit.fields
    elif hasattr(hit, "metadata"):
        d["fields"] = dict(hit.metadata) if not isinstance(hit.metadata, dict) else hit.metadata
    else:
        d["fields"] = {}
    return d


# ---------------------------------------------------------------------------
# Candidate building helpers
# ---------------------------------------------------------------------------

def _build_candidate_items(
    promo_results: dict[str, list[dict]],
    interest_items: list[dict],
) -> list[dict]:
    """Build flat list of candidate items from Pinecone promo results.

    Each candidate is a self-contained dict with all data needed for
    serve-time assembly (prices, dates, store, emoji, etc.).
    """
    # Build interest metrics lookup by normalized_name
    interest_metrics = {}
    for item in interest_items:
        name = item.get("normalized_name", "")
        metrics = item.get("metrics", {})
        interest_metrics[name] = {
            "restock_urgency": metrics.get("restock_urgency"),
            "purchase_frequency_days": metrics.get("purchase_frequency_days"),
            "avg_unit_price": metrics.get("avg_unit_price"),
        }

    seen_keys: set[str] = set()
    candidates: list[dict] = []

    for item_name, promos in promo_results.items():
        item_metrics = interest_metrics.get(item_name, {})
        for promo in promos:
            item_key = promo.get("item_key", "")
            if not item_key or item_key in seen_keys:
                continue
            seen_keys.add(item_key)

            original_price = _coerce_price(promo.get("original_price"))
            promo_price = _coerce_price(promo.get("promo_price"))
            savings_amount = _coerce_price(promo.get("savings_amount"))
            discount_pct = round((savings_amount / original_price) * 100) if original_price > 0 else 0

            store_name = promo.get("source_retailer", "")
            display_name = (promo.get("display_name") or "").strip()
            display_mechanism = (promo.get("display_mechanism") or "").strip()

            candidates.append({
                "item_key": item_key,
                "brand": "",
                "product_name": display_name,
                "original_price": original_price,
                "promo_price": promo_price,
                "savings": savings_amount,
                "discount_percentage": discount_pct,
                "mechanism": display_mechanism,
                "validity_start": promo.get("validity_start", ""),
                "validity_end": promo.get("validity_end", ""),
                "promo_folder_url": promo.get("promo_folder_url"),
                "store_name": store_name,
                "display_name": display_name,
                "display_mechanism": display_mechanism,
                "display_description": promo.get("display_description", ""),
                "display_unit_price": promo.get("display_unit_price"),
                "display_savings_label": promo.get("display_savings_label", ""),
                "savings_amount": savings_amount,
                "granular_category": promo.get("granular_category", ""),
                "relevance_score": promo.get("relevance_score"),
                "restock_urgency": item_metrics.get("restock_urgency"),
                "purchase_frequency_days": item_metrics.get("purchase_frequency_days"),
                "avg_unit_price": item_metrics.get("avg_unit_price"),
            })

    return candidates




def _current_brussels_date() -> date:
    return shared_current_brussels_date()


def _date_to_epoch(date_str: Optional[str]) -> int:
    if not date_str:
        return 0
    try:
        return int(date_str.replace("-", ""))
    except (TypeError, ValueError, AttributeError):
        return 0


def _compute_promo_week(report_date: Optional[date] = None) -> dict:
    return shared_compute_promo_week(report_date)
