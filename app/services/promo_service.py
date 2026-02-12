"""Promo recommendation service.

Retrieves the user's enriched profile, searches Pinecone for matching
promotions, reranks for relevance, and generates personalized
recommendations via Gemini.
"""

import asyncio
import json
import logging
import time
from datetime import date, timedelta, datetime
from typing import Any, Optional

from pinecone import Pinecone
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.repositories.enriched_profile_repo import EnrichedProfileRepository

logger = logging.getLogger(__name__)

# Search tuning
SEARCH_TOP_K = 20
RERANK_TOP_N = 5
RERANK_SCORE_THRESHOLD = 0.55

SYSTEM_PROMPT = """\
You are the user's personal promo hunter inside a Belgian grocery savings app called Scandelicious.
Your job is to analyze matched promotions against the user's shopping habits and return a structured JSON response.

## HARD RULES — never break these
- ONLY reference promotions explicitly present in the provided data. Never invent, guess, or speculate about deals.
- Skip items with zero matching promos silently.
- Every deal must include: brand name, product, exact prices, promo mechanism, store, and validity dates.
- Keep Belgian promo terms as-is: "1+1 Gratis", "-50%", "2+1 Gratis", "Rode Prijzen", etc. — do NOT translate them.
- Use Belgian-style dates: "DD/MM" format (e.g., "09/02").
- All prices are in EUR (numeric values, no € symbol in JSON numbers).

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

## EMOJI GUIDE — use in `emoji` fields
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

## STORE COLORS — use in `store_color` fields
🟦 Carrefour Hypermarkt
🟧 Colruyt
🟩 Delhaize
🟨 Albert Heijn
🟪 Lidl
🟥 Aldi
⬜ Other stores

## OUTPUT — return ONLY a JSON object with this exact structure:

{
  "weekly_savings": <number: total EUR savings across all deals>,
  "deal_count": <number: total deals found>,

  "top_picks": [
    // Up to 3 best deals, ranked by combination of savings amount and relevance to user habits.
    // Prioritize: (1) highest absolute savings, (2) items with high restock_urgency, (3) items bought frequently.
    {
      "brand": "<string>",
      "product_name": "<string: clean product name>",
      "emoji": "<string: category emoji>",
      "store": "<string: retailer name>",
      "original_price": <number>,
      "promo_price": <number>,
      "savings": <number>,
      "discount_percentage": <integer: rounded percentage discount, e.g. 50 for half price, calculated as round((1 - promo_price/original_price) * 100)>,
      "mechanism": "<string: e.g. '1+1 Gratis', '-30%'>",
      "validity_start": "<string: DD/MM — from promo data>",
      "validity_end": "<string: DD/MM>",
      "reason": "<string: one sentence linking deal to user's buying pattern with concrete numbers>",
      "page_number": "<integer or null: pass through EXACTLY from promo data, must be integer not float>",
      "promo_folder_url": "<string or null: pass through EXACTLY from promo data>"
    }
  ],

  "stores": [
    // One object per store that has deals. Ordered by total_savings descending.
    {
      "store_name": "<string>",
      "store_color": "<string: emoji from store colors above>",
      "total_savings": <number>,
      "validity_end": "<string: DD/MM — latest validity_end across items>",
      "items": [
        {
          "brand": "<string>",
          "product_name": "<string>",
          "emoji": "<string: category emoji>",
          "original_price": <number>,
          "promo_price": <number>,
          "savings": <number>,
          "discount_percentage": <integer: rounded percentage discount>,
          "mechanism": "<string>",
          "validity_start": "<string: DD/MM — from promo data>",
          "validity_end": "<string: DD/MM — from promo data>",
          "page_number": "<integer or null: pass through EXACTLY from promo data, must be integer not float>",
          "promo_folder_url": "<string or null: pass through EXACTLY from promo data>"
        }
      ],
      "tip": "<string: one personalized tip for this store trip, referencing user's habits>"
    }
  ],

  "smart_switch": <null or {
    // Suggest swapping ONE premium brand for a cheaper alternative on promo.
    // Only include if savings are meaningful. null if no good switch exists.
    "from_brand": "<string: brand they currently buy>",
    "to_brand": "<string: cheaper alternative on promo>",
    "emoji": "<string: category emoji>",
    "product_type": "<string: what kind of product>",
    "savings": <number>,
    "mechanism": "<string: promo mechanism + store>",
    "reason": "<string: one sentence explaining why the switch makes sense>"
  }>,

  "summary": {
    "total_items": <number>,
    "total_savings": <number>,
    "stores_breakdown": [
      // Same order as stores array
      {"store": "<string>", "items": <number>, "savings": <number>}
    ],
    "best_value_store": "<string: store with highest total savings>",
    "best_value_savings": <number>,
    "best_value_items": <number>,
    "closing_nudge": "<string: one short line referencing their profile — a product they buy often that might get a deal soon, or a spending trend>"
  }
}

## IMPORTANT RULES FOR JSON
- Each deal should appear ONCE — either in top_picks OR in a store's items, not both.
  Top picks are the hero deals shown prominently. Store items are the remaining deals.
- No items without confirmed promos in the data.
- All numeric values must be actual numbers (not strings).
- weekly_savings must equal the sum of all individual deal savings.
- summary.total_savings must equal weekly_savings.
- page_number and promo_folder_url: copy these VERBATIM from the promo data. Never modify, invent, or omit them. Use null if not present in the source data.
- page_number must be an integer (e.g. 13), never a float (e.g. 13.0).
- discount_percentage: always calculate as round((1 - promo_price/original_price) * 100). Must be an integer.
- validity_start and validity_end: copy from promo data in DD/MM format. Include on EVERY deal (top_picks and store items).
- Respond with ONLY valid JSON. No markdown, no code blocks, no extra text."""


class PromoService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.settings = get_settings()
        self.enriched_repo = EnrichedProfileRepository(db)

    async def get_recommendations(self, user_id: str) -> dict:
        """Full pipeline: fetch profile -> search Pinecone -> generate via LLM."""
        # Step 1: Fetch enriched profile
        profile = await self._fetch_enriched_profile(user_id)

        interest_items = profile.get("promo_interest_items", [])
        if not interest_items:
            return self._empty_response()

        # Step 2: Search Pinecone (sync SDK, run in thread pool)
        promo_results = await self._search_all_promos(interest_items)

        # Step 3: Generate LLM recommendations
        recommendations = await self._generate_recommendations(profile, promo_results)
        return recommendations

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

    async def _search_all_promos(self, interest_items: list[dict]) -> dict[str, list[dict]]:
        """Search Pinecone for promotions matching each interest item."""
        pc = Pinecone(api_key=self.settings.PINECONE_API_KEY)
        index = pc.Index(host=self.settings.PINECONE_INDEX_HOST)

        all_results: dict[str, list[dict]] = {}

        for item in interest_items:
            name = item["normalized_name"]
            promos = await asyncio.to_thread(
                _search_promos_for_item, pc, index, item
            )
            all_results[name] = promos

            if promos:
                logger.info(
                    f"Promo search '{name}': {len(promos)} matches "
                    f"(scores: {[p['relevance_score'] for p in promos]})"
                )
            # Small delay to avoid rate limits
            await asyncio.sleep(0.2)

        return all_results

    async def _generate_recommendations(
        self, profile: dict, promo_results: dict[str, list[dict]]
    ) -> dict:
        """Send profile + matched promos to Gemini for recommendation generation."""
        user_message = _build_llm_context(profile, promo_results)
        raw_response = await asyncio.to_thread(
            self._call_gemini, user_message
        )
        return _parse_llm_response(raw_response)

    def _call_gemini(self, user_message: str) -> str:
        from google import genai
        from google.genai import types
        from app.schemas.promo import GeminiPromoOutput

        client = genai.Client(api_key=self.settings.GEMINI_API_KEY)
        response = client.models.generate_content(
            model="gemini-3-pro-preview",
            contents=[user_message],
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                max_output_tokens=8192,
                temperature=0.7,
                response_mime_type="application/json",
                response_schema=GeminiPromoOutput,
            ),
        )
        if response.text is None:
            logger.warning(f"Gemini returned None text. Candidates: {response.candidates}")
            raise GeminiPromoError("Gemini returned empty response — likely blocked by safety filters")
        return response.text

    @staticmethod
    def _empty_response() -> dict:
        return {
            "weekly_savings": 0,
            "deal_count": 0,
            "promo_week": _compute_promo_week(),
            "top_picks": [],
            "stores": [],
            "smart_switch": None,
            "summary": {
                "total_items": 0,
                "total_savings": 0,
                "stores_breakdown": [],
                "best_value_store": None,
                "best_value_savings": 0,
                "best_value_items": 0,
                "closing_nudge": "We need more receipt data to find you deals. Keep scanning!",
            },
        }


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

def _today_epoch() -> int:
    """Return today's date as YYYYMMDD integer for Pinecone filtering."""
    return int(date.today().strftime("%Y%m%d"))


def _is_expired(promo: dict) -> bool:
    """Check if a promo is expired based on its validity_end string (YYYY-MM-DD).

    Safety net for records ingested before validity_end_epoch was added.
    """
    validity_end = promo.get("validity_end", "")
    if not validity_end:
        return False  # No date = keep it (can't determine)
    try:
        end_date = datetime.strptime(validity_end, "%Y-%m-%d").date()
        return end_date < date.today()
    except (ValueError, TypeError):
        return False


def _search_promos_for_item(pc: Pinecone, index, item: dict) -> list[dict]:
    """Search Pinecone for promotions matching a single promo interest item."""
    normalized_name = item["normalized_name"]
    granular_category = item.get("granular_category")
    interest_category = item.get("interest_category")
    brands = item.get("brands", [])

    # Expiration filter: only return promos that haven't expired yet
    expiry_filter = {"validity_end_epoch": {"$gte": _today_epoch()}}

    if granular_category:
        filter_dict = {"$and": [{"granular_category": {"$eq": granular_category}}, expiry_filter]}
    else:
        filter_dict = expiry_filter

    cat_suffix = ""
    if granular_category and granular_category != "Other":
        cat_suffix = f" ({granular_category})"

    # Build query texts
    if interest_category == "brand_loyal" and brands:
        query_texts = [f"{brand} {normalized_name}{cat_suffix}" for brand in brands]
    else:
        query_texts = [f"{normalized_name}{cat_suffix}"]

    # Search + rerank across all queries
    seen_ids: set[str] = set()
    all_results: list[dict] = []

    for query_text in query_texts:
        hits = _pinecone_search_and_rerank(index, query_text, filter_dict)

        # Fallback without category filter (still enforce expiry)
        if not hits and granular_category:
            hits = _pinecone_search_and_rerank(index, query_text, filter_dict=expiry_filter)

        for hit in hits:
            hit_id = hit.get("_id", "")
            if hit_id and hit_id in seen_ids:
                continue
            if hit_id:
                seen_ids.add(hit_id)
            all_results.append(hit)

    # Filter by rerank score threshold + expiration safety net
    relevant = []
    for hit in all_results:
        score = hit.get("_score", 0)
        if score >= RERANK_SCORE_THRESHOLD:
            promo = _build_promo_dict(hit.get("fields", {}), score)
            if _is_valid_promo(promo) and not _is_expired(promo):
                relevant.append(promo)

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
                    if _is_valid_promo(promo) and not _is_expired(promo):
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


def _is_valid_promo(promo: dict) -> bool:
    original = promo.get("original_price")
    promo_price = promo.get("promo_price")
    if original is not None and promo_price is not None:
        try:
            orig_float = float(original)
            promo_float = float(promo_price)
            if orig_float <= 0:
                return False
            if promo_float > orig_float:
                return False
        except (ValueError, TypeError):
            pass
    return True


def _build_promo_dict(fields: dict, score: float) -> dict:
    return {
        "relevance_score": round(score, 4),
        "normalized_name": fields.get("normalized_name", ""),
        "original_description": fields.get("original_description", ""),
        "brand": fields.get("brand", ""),
        "granular_category": fields.get("granular_category", ""),
        "parent_category": fields.get("parent_category", ""),
        "original_price": fields.get("original_price"),
        "promo_price": fields.get("promo_price"),
        "promo_mechanism": fields.get("promo_mechanism", ""),
        "unit_info": fields.get("unit_info", ""),
        "validity_start": fields.get("validity_start", ""),
        "validity_end": fields.get("validity_end", ""),
        "source_retailer": fields.get("source_retailer", ""),
        "page_number": fields.get("page_number"),
        "promo_folder_url": fields.get("promo_folder_url"),
    }


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

    if habits.get("avg_health_score") is not None:
        parts.append(
            f"Health score: {habits['avg_health_score']}/5 | "
            f"Premium ratio: {habits.get('premium_brand_ratio', 0):.0%}"
        )

    ht = habits.get("health_trend")
    if ht and ht.get("trend"):
        parts.append(
            f"Health trend: {ht['trend']} "
            f"(4w avg: {ht.get('current_4w_avg', '?')} vs prev: {ht.get('previous_4w_avg', '?')})"
        )
        parts.append(
            f"Fresh produce: {ht.get('fresh_produce_pct', 0)}% of food | "
            f"Ready meals: {ht.get('ready_meals_pct', 0)}%"
        )

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


def _parse_llm_response(raw_response: str) -> dict:
    """Parse Gemini's structured JSON output and apply server-side fixups.

    With response_schema enforced, Gemini guarantees valid JSON matching
    GeminiPromoOutput. We still apply fixups for page_number (int coercion)
    and discount_percentage (server-side recalculation for accuracy).
    """
    import re
    from pydantic import ValidationError
    from app.schemas.promo import GeminiPromoOutput

    clean = raw_response.strip()
    if clean.startswith("```"):
        clean = clean.split("```", 2)[1]
        if clean.startswith("json"):
            clean = clean[4:]
        clean = clean.strip()

    # Safety net: strip trailing commas
    clean = re.sub(r',\s*([}\]])', r'\1', clean)

    # Parse and validate through Pydantic schema
    try:
        validated = GeminiPromoOutput.model_validate_json(clean)
        data = validated.model_dump()
    except (ValidationError, ValueError) as e:
        logger.warning(f"Pydantic validation failed, falling back to loose parse: {e}")
        try:
            data = json.loads(clean, strict=False)
        except json.JSONDecodeError as e2:
            logger.error(f"Failed to parse LLM JSON response: {e2}")
            logger.error(f"Raw response (first 500 chars): {raw_response[:500]}")
            return _empty_fallback()

    # Cap top_picks at 3
    data["top_picks"] = data.get("top_picks", [])[:3]

    # Server-side fixups: page_number -> int, discount_percentage recalculation
    for pick in data.get("top_picks", []):
        _fix_page_number(pick)
        _ensure_discount_percentage(pick)

    for store in data.get("stores", []):
        for item in store.get("items", []):
            _fix_page_number(item)
            _ensure_discount_percentage(item)

    # Add promo_week context (computed server-side, not by LLM)
    data["promo_week"] = _compute_promo_week()

    return data


def _empty_fallback() -> dict:
    """Minimal valid response when LLM output can't be parsed."""
    return {
        "weekly_savings": 0,
        "deal_count": 0,
        "promo_week": _compute_promo_week(),
        "top_picks": [],
        "stores": [],
        "smart_switch": None,
        "summary": {
            "total_items": 0,
            "total_savings": 0,
            "stores_breakdown": [],
            "best_value_store": None,
            "best_value_savings": 0,
            "best_value_items": 0,
            "closing_nudge": "Could not generate recommendations — try again later.",
        },
    }


def _fix_page_number(item: dict) -> None:
    """Coerce page_number to int (Pinecone stores it as float)."""
    pn = item.get("page_number")
    if pn is not None:
        try:
            item["page_number"] = int(pn)
        except (ValueError, TypeError):
            item["page_number"] = None
    else:
        item["page_number"] = None


def _ensure_discount_percentage(item: dict) -> None:
    """Compute discount_percentage if LLM didn't provide it or got it wrong."""
    orig = item.get("original_price", 0)
    promo = item.get("promo_price", 0)
    if orig and orig > 0 and promo is not None:
        item["discount_percentage"] = round((1 - promo / orig) * 100)
    else:
        item.setdefault("discount_percentage", 0)


def _compute_promo_week() -> dict:
    """Return the current promo week (Mon-Sun) as start/end/label."""
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)
    return {
        "start": monday.strftime("%d/%m"),
        "end": sunday.strftime("%d/%m"),
        "label": f"Week {today.isocalendar()[1]}",
    }
