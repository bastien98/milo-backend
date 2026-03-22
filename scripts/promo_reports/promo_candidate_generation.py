"""Offline promo candidate generation service.

Retrieves the user's enriched profile, searches Pinecone for matching
promotions, reranks for relevance, and generates personalized
candidate annotations via Gemini.
"""

import asyncio
import hashlib
import json
import logging
import time
from datetime import date, timedelta
from typing import Any, List, Optional

from pinecone import Pinecone
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import select

from app.core.promo_reports import (
    build_empty_promo_response,
    compute_promo_week as shared_compute_promo_week,
    current_brussels_date as shared_current_brussels_date,
)
from app.config import get_settings
from app.db.repositories.enriched_profile_repo import EnrichedProfileRepository
from app.models.enums import Language, PromoReportStatus
from app.models.user import User
from app.models.user_profile import UserProfile

logger = logging.getLogger(__name__)

# Search tuning
SEARCH_TOP_K = 20
RERANK_TOP_N = 5
RERANK_SCORE_THRESHOLD = 0.55

SYSTEM_PROMPT = """\
You are the user's personal promo hunter inside a Belgian grocery savings app called Scandelicious.
Your job is to annotate matched promotions with personalized text based on the user's shopping habits.

## HARD RULES — never break these
- ONLY reference promotions explicitly present in the provided data. Never invent, guess, or speculate about deals.
- item_key values: copy EXACTLY from the promo data. Never invent or alter them.
- Keep Belgian promo terms as-is: "1+1 Gratis", "-50%", "2+1 Gratis", "Rode Prijzen", etc. — do NOT translate them.
- Brand names: use EXACTLY as provided in the user data. Never rename, simplify, or rephrase brand names.

## UNDERSTANDING USER METRICS
Each interest item includes a `metrics` block with the user's purchase history:
- `restock_urgency`: Ratio of days_since / purchase_frequency. **Use this to prioritize deals:**
  - >=1.5: OVERDUE — highlight urgently
  - >=1.0: DUE NOW — good timing
  - >=0.7: due soon — worth mentioning
  - <0.7 or null: not urgent yet
- `avg_units_per_trip`, `avg_unit_price`, `purchase_frequency_days`: use these for personalized insights
- **Null values** mean insufficient data — don't reference specific numbers when null.

Items marked [CATEGORY FALLBACK] represent broader category interests — personalize based on category.

## TONE FOR TEXT FIELDS
- Second person ("you"). Confident, punchy, warm. Short sentences.
- No corporate speak. No filler. No apologies.

## EMOJI GUIDE — use in `emoji` fields for smart_switch_candidates
🧊 Drinks (tea, soda, water, juice)
🥛 Dairy (milk, yoghurt, skyr, cheese)
🐟 Fish & Seafood
🍗 Meat & Poultry
🍝 Pasta, Rice & Meals
🍕 Frozen (pizza, snacks, meals)
🍎 Fruit
🥬 Vegetables & Salad
🥜 Nuts & Snacks
🍞 Bread & Bakery
🧴 Household & Personal Care
🧀 Cheese (when main item)
🍫 Sweets & Chocolate
🍺 Alcohol

## OUTPUT — return ONLY a JSON object with this exact structure:

{
  "item_annotations": [
    // One annotation per matched promo item. Include ALL items from the matched promotions data.
    {
      "item_key": "<string: copy EXACTLY from promo data>",
      "reason": "<string: one sentence linking this deal to the user's buying pattern with concrete numbers>"
    }
  ],

  "store_tips": [
    // One tip per store that has matched promotions.
    {
      "store_name": "<string: retailer name>",
      "tip": "<string: one personalized tip for this store trip, referencing user's habits>"
    }
  ],

  "smart_switch_candidates": [
    // 0-3 brand swap suggestions. Only include if savings are meaningful. Empty array if no good switches.
    {
      "from_brand": "<string: brand they currently buy>",
      "to_brand": "<string: cheaper alternative on promo>",
      "emoji": "<string: category emoji>",
      "product_type": "<string: what kind of product>",
      "savings": <number>,
      "mechanism": "<string: promo mechanism + store>",
      "store_name": "<string: retailer where the alternative is on promo>",
      "reason": "<string: one sentence explaining why the switch makes sense>"
    }
  ],

  "closing_nudge": "<string: one short line referencing their profile — a product they buy often or a spending trend>"
}

## IMPORTANT RULES FOR JSON
- item_annotations must cover every promo item from the matched promotions. Use the item_key exactly as provided.
- store_tips: one entry per unique store in the matched promotions.
- smart_switch_candidates: only suggest switches between brands where a cheaper alternative is currently on promo.
- All numeric values must be actual numbers (not strings).
- Respond with ONLY valid JSON. No markdown, no code blocks, no extra text."""


class PromoCandidateGenerationService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.settings = get_settings()
        self.enriched_repo = EnrichedProfileRepository(db)
        self._pc = Pinecone(api_key=self.settings.PINECONE_API_KEY)
        self._pinecone_index = self._pc.Index(host=self.settings.PINECONE_INDEX_HOST)

    async def _fetch_user_profile_prefs(self, user_id: str) -> tuple[Optional[Language], Optional[List[str]]]:
        """Fetch the user's language and preferred stores from their profile."""
        result = await self.db.execute(
            select(UserProfile.language, UserProfile.preferred_stores)
            .join(User, User.firebase_uid == UserProfile.user_id)
            .where(User.id == user_id)
        )
        row = result.one_or_none()
        if row:
            return row[0], row[1]
        return None, None

    async def build_weekly_candidates(
        self,
        user_id: str,
        report_date: Optional[date] = None,
    ) -> Optional[dict]:
        """Build a weekly candidate pool: search all stores, annotate with Gemini.

        Returns a dict with:
          - candidates: list of candidate item dicts (all stores, with AI annotations)
          - closing_nudge: str
          - smart_switch_candidates: list of smart switch dicts
          - store_tips: dict of store_name -> tip
          - interest_item_count: int
          - total_matches: int
          - profile: enriched profile dict (for metadata)

        Returns None if the user has no interest items or no matches.
        """
        report_date = report_date or _current_brussels_date()
        report_date_epoch = _date_to_epoch(report_date.isoformat())

        profile = await self._fetch_enriched_profile(user_id)
        interest_items = profile.get("promo_interest_items", [])
        if not interest_items:
            return None

        language, _preferred_stores = await self._fetch_user_profile_prefs(user_id)
        # Search ALL stores — no filtering by preferred_stores
        promo_results = await self._search_all_promos(interest_items, report_date_epoch)

        if not any(promo_results.values()):
            return None

        # Build flat list of candidate items from Pinecone results
        candidates = _build_candidate_items(promo_results, interest_items)
        if not candidates:
            return None

        # Get AI annotations from Gemini
        annotations = await self._generate_annotations(
            profile, promo_results, language=language
        )

        # Merge annotations onto candidates
        _merge_annotations(candidates, annotations)

        # Build store_tips dict
        store_tips = {}
        for st in annotations.get("store_tips", []):
            store_tips[st["store_name"]] = st["tip"]

        return {
            "candidates": candidates,
            "closing_nudge": annotations.get("closing_nudge", ""),
            "smart_switch_candidates": annotations.get("smart_switch_candidates", []),
            "store_tips": store_tips,
            "interest_item_count": len(interest_items),
            "total_matches": len(candidates),
            "profile": profile,
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

    async def _generate_annotations(
        self, profile: dict, promo_results: dict[str, list[dict]],
        language: Optional[Language] = None,
    ) -> dict:
        """Send profile + matched promos to Gemini for per-item annotation."""
        user_message = _build_llm_context(profile, promo_results)
        raw_response = await asyncio.to_thread(
            self._call_gemini, user_message, 1, language
        )
        return _parse_annotation_response(raw_response)

    def _call_gemini(
        self, user_message: str, attempt: int = 1,
        language: Optional[Language] = None,
    ) -> str:
        from google import genai
        from google.genai import types
        from app.schemas.promo import GeminiCandidateOutput

        system_prompt = SYSTEM_PROMPT
        if language and language.value == "nl":
            system_prompt += "\n\nCRITICAL LANGUAGE RULE: ALL text fields (reason, tip, closing_nudge, smart_switch reason) MUST be written in Flemish Dutch (Vlaams Nederlands). Use natural Belgian Dutch. Keep promo mechanisms in their original form (1+1 Gratis, -50%, etc). Product names and brand names stay as-is. Only the descriptive/personalized text fields must be in Dutch."
        elif language and language.value == "fr":
            system_prompt += "\n\nCRITICAL LANGUAGE RULE: ALL text fields (reason, tip, closing_nudge, smart_switch reason) MUST be written in French (Belgian French). Keep promo mechanisms in their original form. Product names and brand names stay as-is. Only the descriptive/personalized text fields must be in French."

        client = genai.Client(api_key=self.settings.GEMINI_API_KEY)
        response = client.models.generate_content(
            model="gemini-3-pro-preview",
            contents=[user_message],
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                max_output_tokens=16384,
                temperature=0.7,
                response_mime_type="application/json",
                response_schema=GeminiCandidateOutput,
            ),
        )
        if response.text is None:
            logger.warning(f"Gemini returned None text. Candidates: {response.candidates}")
            raise GeminiPromoError("Gemini returned empty response — likely blocked by safety filters")

        raw = response.text.strip()
        try:
            json.loads(raw)
        except json.JSONDecodeError:
            if attempt < 2:
                logger.warning(f"Gemini returned truncated JSON (attempt {attempt}), retrying...")
                time.sleep(1)
                return self._call_gemini(user_message, attempt + 1, language)
            raise GeminiPromoError("Gemini returned truncated JSON on final attempt")

        return response.text


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class ProfileNotFoundError(Exception):
    def __init__(self, user_id: str):
        self.user_id = user_id
        super().__init__(f"No enriched profile found for user {user_id}")


class GeminiPromoError(Exception):
    pass


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

    # Keep only brands the user actually buys.
    # Skip filtering for housebrand items (unbranded deli/bakery) — no promo
    # will ever match those placeholders, so let semantic relevance decide.
    def _is_housebrand(b: str) -> bool:
        return b == "in-house" or b.endswith("-housebrand")

    allowed_brands: set[str] = set()
    item_brands = item.get("brands") or []
    is_housebrand_only = not item_brands or all(_is_housebrand(b) for b in item_brands)
    if not is_housebrand_only:
        if interest_category == "price_switcher":
            allowed_brands = {b.lower() for b in (item.get("category_brands") or item_brands)}
        elif interest_category != "category_fallback":
            allowed_brands = {b.lower() for b in item_brands}
        allowed_brands = {b for b in allowed_brands if not _is_housebrand(b)}
    if allowed_brands:
        relevant = [p for p in relevant if p["brand"].lower() in allowed_brands]

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
            if allowed_brands:
                relevant = [p for p in relevant if p["brand"].lower() in allowed_brands]
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
    # Require display-ready fields (preferred) or fall back to legacy fields
    display_name = (promo.get("display_name") or "").strip()
    display_mechanism = (promo.get("display_mechanism") or "").strip()
    # Fall back to legacy fields for records ingested before the display fields existed
    product_label = display_name or (promo.get("original_description") or promo.get("normalized_name") or "").strip()
    mechanism = display_mechanism or (promo.get("promo_mechanism") or "").strip()
    retailer = (promo.get("source_retailer") or "").strip()
    if not product_label or not mechanism or not retailer:
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

    # Prices are optional — but validate if both are present
    original = _safe_price(promo.get("original_price"))
    promo_price = _safe_price(promo.get("promo_price"))
    if original is not None and promo_price is not None:
        if original <= 0 or promo_price <= 0:
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
            (fields.get("normalized_name") or fields.get("original_description") or "").strip().lower(),
            (fields.get("source_retailer") or "").strip().lower(),
            (fields.get("promo_mechanism") or "").strip().lower(),
            f"{original_price:.2f}",
            f"{promo_price:.2f}",
            str(fields.get("validity_start") or ""),
            str(fields.get("validity_end") or ""),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _build_promo_dict(fields: dict, score: float) -> dict:
    # Support both old field name ("brand") and new ("normalized_brand")
    brand = fields.get("normalized_brand") or fields.get("brand", "")
    promo = {
        "relevance_score": round(score, 4),
        "item_key": _build_item_key(fields),
        "normalized_name": fields.get("normalized_name", ""),
        "original_description": fields.get("original_description", ""),
        "brand": brand,
        "is_premium": fields.get("is_premium", False),
        "packaging_type": fields.get("packaging_type", ""),
        "granular_category": fields.get("granular_category", ""),
        "parent_category": fields.get("parent_category", ""),
        "original_price": fields.get("original_price"),
        "promo_price": fields.get("promo_price"),
        "promo_mechanism": fields.get("promo_mechanism", ""),
        "pack_size": fields.get("pack_size"),
        "content_value": fields.get("content_value"),
        "content_unit": fields.get("content_unit", ""),
        "unit_info": fields.get("unit_info", ""),
        "validity_start": fields.get("validity_start", ""),
        "validity_end": fields.get("validity_end", ""),
        "validity_start_epoch": fields.get("validity_start_epoch"),
        "validity_end_epoch": fields.get("validity_end_epoch"),
        "source_retailer": fields.get("source_retailer", ""),
        "page_number": fields.get("page_number"),
        "promo_folder_url": fields.get("promo_folder_url"),
        "display_name": fields.get("display_name", ""),
        "display_mechanism": fields.get("display_mechanism", ""),
        "display_description": fields.get("display_description", ""),
        "display_unit_price": fields.get("display_unit_price"),
        "display_savings_label": fields.get("display_savings_label"),
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
# LLM context builder + response parser
# ---------------------------------------------------------------------------

def _build_llm_context(profile: dict, promo_results: dict[str, list[dict]]) -> str:
    habits = profile["shopping_habits"]
    parts = []

    # Section 1: Compact user profile
    parts.append("## USER PROFILE")
    parts.append(
        f"Receipts: {profile['receipts_analyzed']} "
        f"({profile['data_period_start']} to {profile['data_period_end']})"
    )
    parts.append(
        f"Total spend: €{habits.get('total_spend', 0):.2f} | "
        f"Avg receipt: €{habits.get('avg_receipt_total', 0):.2f} | "
        f"{habits.get('shopping_frequency_per_week', 0)}x/week"
    )

    stores = habits.get("preferred_stores", [])
    if stores:
        store_lines = [
            f"  {s['name']}: €{s['spend']:.2f} ({s['pct']}%, {s['visits']} visits)"
            for s in stores[:5]
        ]
        parts.append("Stores:\n" + "\n".join(store_lines))

    ss = habits.get("savings_summary")
    if ss:
        parts.append(
            f"Current savings: €{ss['total_saved']:.2f} total "
            f"({ss['savings_rate_pct']}% rate, ~€{ss['monthly_savings_avg']:.2f}/mo)"
        )

    bsp = habits.get("brand_savings_potential")
    if bsp:
        parts.append(
            f"Brand split: €{bsp['premium_spend']:.2f} premium / "
            f"€{bsp['house_brand_spend']:.2f} house brand / "
            f"€{bsp['unbranded_spend']:.2f} unbranded"
        )
        if bsp["estimated_monthly_savings_if_switch"] > 0:
            parts.append(
                f"Potential savings switching to house brands: "
                f"€{bsp['estimated_monthly_savings_if_switch']:.2f}/mo"
            )

    ind = habits.get("indulgence_tracker")
    if ind and ind.get("total_indulgence", 0) > 0:
        parts.append(
            f"Indulgence: €{ind['total_indulgence']:.2f} "
            f"({ind['indulgence_pct']}%) — ~€{ind['estimated_yearly']:.0f}/yr"
        )

    sl = habits.get("store_loyalty")
    if sl:
        parts.append(
            f"Store concentration: {sl['concentration_score']:.2f} HHI | "
            f"{sl['stores_visited_count']} stores visited"
        )

    se = habits.get("shopping_efficiency")
    if se:
        parts.append(
            f"Small trips (<5 items): {se['small_trips_count']} "
            f"({se['small_trips_pct']}%), avg €{se['small_trips_avg_cost']:.2f}"
        )
        if se.get("weekend_premium_pct", 0) != 0:
            parts.append(f"Weekend premium: {se['weekend_premium_pct']:+.1f}% vs weekday")

    # Section 2: Interest items with metrics
    parts.append("\n## ITEMS TO FIND DEALS FOR")
    parts.append("(Note: null metrics indicate insufficient data for that calculation)")
    for item in profile["promo_interest_items"]:
        name = item.get("normalized_name", "?")
        brands = ", ".join(item.get("brands", [])) or "no brand"
        tags = item.get("tags", [])
        metrics = item.get("metrics", {})
        is_fallback = item.get("is_category_fallback", False)

        metrics_parts = []
        if metrics.get("total_spend") is not None:
            metrics_parts.append(f"€{metrics['total_spend']:.2f} spent")
        if metrics.get("trip_count") is not None:
            metrics_parts.append(f"{metrics['trip_count']} trips")
        if metrics.get("avg_units_per_trip") is not None:
            metrics_parts.append(f"~{metrics['avg_units_per_trip']} units/trip")
        if metrics.get("avg_unit_price") is not None:
            metrics_parts.append(f"€{metrics['avg_unit_price']:.2f}/unit")
        if metrics.get("purchase_frequency_days") is not None:
            metrics_parts.append(f"every ~{metrics['purchase_frequency_days']}d")

        restock_urgency = metrics.get("restock_urgency")
        urgency_str = ""
        if restock_urgency is not None:
            if restock_urgency >= 1.5:
                urgency_str = f" | OVERDUE (urgency {restock_urgency:.1f})"
            elif restock_urgency >= 1.0:
                urgency_str = f" | DUE NOW (urgency {restock_urgency:.1f})"
            elif restock_urgency >= 0.7:
                urgency_str = f" | due soon (urgency {restock_urgency:.1f})"

        metrics_str = " | ".join(metrics_parts) if metrics_parts else "limited data"
        fallback_str = " [CATEGORY FALLBACK]" if is_fallback else ""
        category = item.get("interest_category", "?")
        tags_str = ", ".join(tags) if tags else "none"

        parts.append(
            f"- **{name}** [{item.get('granular_category', '?')}]{fallback_str}\n"
            f"  brands={brands} | category={category} | tags={tags_str}\n"
            f"  {metrics_str}{urgency_str}"
        )

    # Section 3: Matched promotions
    parts.append("\n## MATCHED PROMOTIONS")
    items_with_promos = 0
    total_promos = 0

    for item_name, promos in promo_results.items():
        if not promos:
            continue
        items_with_promos += 1
        parts.append(f"\n### {item_name}")
        for p in promos:
            total_promos += 1
            savings_str = ""
            if p.get("original_price") and p.get("promo_price"):
                try:
                    savings = float(p["original_price"]) - float(p["promo_price"])
                    savings_str = f" (save €{savings:.2f})"
                except (ValueError, TypeError):
                    pass

            page_str = f" | page={p['page_number']}" if p.get("page_number") else ""
            folder_str = (
                f" | folder_url={p['promo_folder_url']}" if p.get("promo_folder_url") else ""
            )

            parts.append(
                f"- {p.get('brand', '?')} · "
                f"{p.get('original_description', p.get('normalized_name', '?'))}\n"
                f"  item_key={p.get('item_key', '?')}\n"
                f"  €{p.get('original_price', '?')} → €{p.get('promo_price', '?')}"
                f"{savings_str} | {p.get('promo_mechanism', '?')}\n"
                f"  {p.get('source_retailer', '?')} | {p.get('unit_info') or '?'} | "
                f"{p.get('validity_start', '?')} to {p.get('validity_end', '?')}"
                f"{page_str}{folder_str}"
            )

    parts.append(
        f"\n**{total_promos} promos matched across "
        f"{items_with_promos}/{len(promo_results)} items.**"
    )
    parts.append("\nGenerate the weekly promo briefing now.")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Candidate building helpers
# ---------------------------------------------------------------------------

# Category → emoji mapping (deterministic, no LLM needed)
_CATEGORY_EMOJI_MAP = {
    "drinks": "🧊", "tea": "🧊", "soda": "🧊", "water": "🧊", "juice": "🧊",
    "dairy": "🥛", "milk": "🥛", "yoghurt": "🥛", "skyr": "🥛",
    "fish": "🐟", "seafood": "🐟",
    "meat": "🍗", "poultry": "🍗",
    "pasta": "🍝", "rice": "🍝", "meals": "🍝",
    "frozen": "🍕",
    "fruit": "🍎",
    "vegetables": "🥬", "salad": "🥬",
    "nuts": "🥜", "snacks": "🥜",
    "bread": "🍞", "bakery": "🍞",
    "household": "🧴", "personal care": "🧴",
    "cheese": "🧀",
    "sweets": "🍫", "chocolate": "🍫",
    "alcohol": "🍺", "beer": "🍺", "wine": "🍺",
}

_STORE_COLOR_MAP = {
    "carrefour hypermarkt": "🟦", "carrefour hyper": "🟦", "carrefour market": "🟦",
    "colruyt": "🟧",
    "delhaize": "🟩", "proxy delhaize": "🟩",
    "albert heijn": "🟨",
    "lidl": "🟪",
    "aldi": "🟥",
    "okay": "🟧",
    "spar": "⬜",
    "intermarché": "⬜", "intermarche": "⬜",
    "jumbo": "⬜",
    "makro": "⬜",
}


def _get_emoji_for_category(granular_category: str, parent_category: str) -> str:
    """Deterministic emoji lookup based on category."""
    for cat in (granular_category, parent_category):
        if not cat:
            continue
        cat_lower = cat.lower()
        for keyword, emoji in _CATEGORY_EMOJI_MAP.items():
            if keyword in cat_lower:
                return emoji
    return "🛒"


def _get_store_color(store_name: str) -> str:
    """Deterministic store color emoji lookup."""
    return _STORE_COLOR_MAP.get(store_name.lower(), "⬜")


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
            has_prices = original_price > 0 and promo_price > 0
            savings = round(original_price - promo_price, 2) if has_prices else 0
            discount_pct = round((1 - promo_price / original_price) * 100) if has_prices and original_price > 0 else 0

            # Coerce page_number to int
            page_number = promo.get("page_number")
            if page_number is not None:
                try:
                    page_number = int(page_number)
                except (ValueError, TypeError):
                    page_number = None

            store_name = promo.get("source_retailer", "")
            granular_category = promo.get("granular_category", "")
            parent_category = promo.get("parent_category", "")

            # Use display_name if available, fall back to legacy fields
            display_name = (promo.get("display_name") or "").strip()
            product_name = display_name or (
                promo.get("original_description")
                or promo.get("normalized_name", "")
            ).strip()

            display_mechanism = (promo.get("display_mechanism") or "").strip()
            mechanism = display_mechanism or promo.get("promo_mechanism", "")

            candidates.append({
                "item_key": item_key,
                "brand": promo.get("brand", ""),
                "product_name": product_name,
                "emoji": _get_emoji_for_category(granular_category, parent_category),
                "original_price": original_price,
                "promo_price": promo_price,
                "savings": savings,
                "discount_percentage": discount_pct,
                "mechanism": mechanism,
                "validity_start": promo.get("validity_start", ""),
                "validity_end": promo.get("validity_end", ""),
                "page_number": page_number,
                "promo_folder_url": promo.get("promo_folder_url"),
                "store_name": store_name,
                "display_name": display_name,
                "display_mechanism": display_mechanism,
                "display_description": promo.get("display_description", ""),
                "display_unit_price": promo.get("display_unit_price"),
                "display_savings_label": promo.get("display_savings_label"),
                "store_color": _get_store_color(store_name),
                "granular_category": granular_category,
                "relevance_score": promo.get("relevance_score"),
                "restock_urgency": item_metrics.get("restock_urgency"),
                "purchase_frequency_days": item_metrics.get("purchase_frequency_days"),
                "avg_unit_price": item_metrics.get("avg_unit_price"),
                "reason": "",  # filled by Gemini annotation
            })

    return candidates


def _merge_annotations(candidates: list[dict], annotations: dict) -> None:
    """Merge Gemini's per-item annotations (reason) onto candidate items in-place."""
    annotation_map = {
        a["item_key"]: a["reason"]
        for a in annotations.get("item_annotations", [])
        if a.get("item_key")
    }
    for candidate in candidates:
        reason = annotation_map.get(candidate["item_key"], "")
        if reason:
            candidate["reason"] = reason


def _parse_annotation_response(raw_response: str) -> dict:
    """Parse Gemini's per-item annotation JSON output."""
    import re
    from pydantic import ValidationError
    from app.schemas.promo import GeminiCandidateOutput

    clean = raw_response.strip()
    if clean.startswith("```"):
        clean = clean.split("```", 2)[1]
        if clean.startswith("json"):
            clean = clean[4:]
        clean = clean.strip()

    clean = re.sub(r',\s*([}\]])', r'\1', clean)

    try:
        validated = GeminiCandidateOutput.model_validate_json(clean)
        data = validated.model_dump()
    except (ValidationError, ValueError) as e:
        logger.warning(f"Pydantic validation of annotations failed, falling back to loose parse: {e}")
        try:
            data = json.loads(clean, strict=False)
        except json.JSONDecodeError as e2:
            logger.error(f"Annotation JSON parse failed: {e2}")
            logger.error(f"Raw response (first 500 chars): {raw_response[:500]}")
            return _empty_annotation_fallback()

    return data


def _empty_annotation_fallback() -> dict:
    """Minimal valid annotation response when LLM output can't be parsed."""
    return {
        "item_annotations": [],
        "store_tips": [],
        "smart_switch_candidates": [],
        "closing_nudge": "",
    }




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
