#!/usr/bin/env python3
"""
Promo Recommender Testbench

Retrieves a user's enriched profile from the production PostgreSQL database,
searches Pinecone's promos index for matching promotions using semantic search
with the normalized_name field, filters by granular_category, reranks results
for high relevance, then generates personalized promo recommendations via LLM.

Pipeline:
  1. Fetch enriched profile (promo_interest_items) from production DB
  2. For each interest item:
     - Semantic search in Pinecone (llama-text-embed-v2) using normalized_name
     - Metadata filter on granular_category
     - Rerank with pinecone-rerank-v0, keep only high-relevance hits
  3. Pass user profile + all matched promotions to LLM for expert analysis

Usage (from scandelicious-backend/):
    python testbench/promo_recommender.py
"""

import asyncio
import json
import logging
import os
import ssl
import sys
import time
from datetime import date
from pathlib import Path

# ---------------------------------------------------------------------------
# SSL fix — must happen before any HTTPS library is imported.
# macOS pyenv Python often lacks access to the system CA store.
# ---------------------------------------------------------------------------
import certifi

os.environ["SSL_CERT_FILE"] = certifi.where()
os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()

# Patch urllib3's default cert location so Pinecone's HTTP pool uses certifi
import urllib3.util.ssl_

urllib3.util.ssl_.DEFAULT_CERTS = certifi.where()  # type: ignore[attr-defined]

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from dotenv import load_dotenv

load_dotenv(BACKEND_ROOT / ".env")

import asyncpg
from pinecone import Pinecone

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
USER_ID = os.environ.get("TEST_USER_ID", "c9b6bc31-d05a-4ab4-97fc-f40ff5fe6f67")

# Production database
DB_CONFIG = {
    "host": "switchback.proxy.rlwy.net",
    "port": 45896,
    "user": "postgres",
    "password": "hrGaUOZtYDDNPUDPmXlzpnVAReIgxlkx",
    "database": "railway",
}

# Pinecone
PINECONE_API_KEY = os.environ.get("PINECONE_API_KEY", "")
PINECONE_INDEX_HOST = "promos-k16b2f4.svc.aped-4627-b74a.pinecone.io"

# Search tuning
SEARCH_TOP_K = 20  # Initial candidates per item from vector search
RERANK_TOP_N = 5  # Max results after reranking
RERANK_SCORE_THRESHOLD = 0.55  # Min relevance score to keep

# LLM
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Step 1: Fetch enriched profile from production DB
# ---------------------------------------------------------------------------
async def fetch_enriched_profile(user_id: str) -> dict:
    """Connect to production PostgreSQL and retrieve the user's enriched profile."""
    conn = await asyncpg.connect(**DB_CONFIG)
    try:
        row = await conn.fetchrow(
            """
            SELECT shopping_habits, promo_interest_items,
                   data_period_start, data_period_end, receipts_analyzed
            FROM user_enriched_profiles
            WHERE user_id = $1
            """,
            user_id,
        )
        if not row:
            raise ValueError(f"No enriched profile found for user {user_id}")

        # asyncpg returns JSONB as dicts/lists directly
        shopping_habits = row["shopping_habits"]
        promo_interest_items = row["promo_interest_items"]
        if isinstance(shopping_habits, str):
            shopping_habits = json.loads(shopping_habits)
        if isinstance(promo_interest_items, str):
            promo_interest_items = json.loads(promo_interest_items)

        return {
            "shopping_habits": shopping_habits,
            "promo_interest_items": promo_interest_items,
            "data_period_start": str(row["data_period_start"]) if row["data_period_start"] else None,
            "data_period_end": str(row["data_period_end"]) if row["data_period_end"] else None,
            "receipts_analyzed": row["receipts_analyzed"],
        }
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# Step 2: Pinecone search + rerank
# ---------------------------------------------------------------------------
def search_promos_for_item(pc: Pinecone, index, item: dict) -> list[dict]:
    """Search Pinecone for promotions matching a single promo interest item.

    Uses integrated search+rerank (single API call) which passes the raw vector
    hits through the reranker server-side — matching the Pinecone console behavior.

    For brand_loyal items: runs one search per brand using {Brand} {Name} ({Category}),
    then deduplicates hits across all brand queries.

    For all other items: searches using {Name} ({Category}).

    If no results pass the threshold, falls back to broader category-based search.
    """
    normalized_name = item["normalized_name"]
    granular_category = item.get("granular_category")
    interest_category = item.get("interest_category")
    brands = item.get("brands", [])

    # Metadata filter
    # NOTE: validity_end is stored as a string in Pinecone, so $gte won't work
    # (Pinecone requires numeric operands for $gte). Skip date filtering for now.
    if granular_category:
        filter_dict = {"granular_category": {"$eq": granular_category}}
    else:
        filter_dict = None

    # Build category suffix for query text
    cat_suffix = ""
    if granular_category and granular_category != "Other":
        cat_suffix = f" ({granular_category})"

    # --- Build query texts ---
    if interest_category == "brand_loyal" and brands:
        query_texts = [f"{brand} {normalized_name}{cat_suffix}" for brand in brands]
    else:
        query_texts = [f"{normalized_name}{cat_suffix}"]

    # --- Integrated search + rerank across all queries ---
    seen_ids: set[str] = set()
    all_results: list[dict] = []

    for query_text in query_texts:
        hits = _pinecone_search_and_rerank(index, query_text, filter_dict)

        # Fallback without category filter
        if not hits and granular_category:
            logger.info(f"    No results with category filter for '{query_text}', retrying without category...")
            hits = _pinecone_search_and_rerank(index, query_text, filter_dict=None)

        # Deduplicate across brand queries
        for hit in hits:
            hit_id = hit.get("_id", "")
            if hit_id and hit_id in seen_ids:
                continue
            if hit_id:
                seen_ids.add(hit_id)
            all_results.append(hit)

    # Filter by rerank score threshold and build promo dicts
    relevant = []
    for hit in all_results:
        score = hit.get("_score", 0)
        if score >= RERANK_SCORE_THRESHOLD:
            promo = _build_promo_dict(hit.get("fields", {}), score)
            # Filter out promos with bad pricing data
            if _is_valid_promo(promo):
                relevant.append(promo)

    # --- Fallback: if no results above threshold, try broader category search ---
    if not relevant and granular_category and interest_category != "category_fallback":
        # Use category name as a broader search term (e.g., "salami" from "Salami & Sausage")
        category_term = granular_category.split(" & ")[0].lower()  # "Salami & Sausage" -> "salami"
        if category_term != normalized_name:
            logger.info(f"    No high-relevance matches, trying broader search with '{category_term}'...")
            fallback_hits = _pinecone_search_and_rerank(index, f"{category_term}{cat_suffix}", filter_dict)
            for hit in fallback_hits:
                score = hit.get("_score", 0)
                if score >= RERANK_SCORE_THRESHOLD:
                    promo = _build_promo_dict(hit.get("fields", {}), score)
                    if _is_valid_promo(promo):
                        relevant.append(promo)
            relevant = relevant[:RERANK_TOP_N]

    return relevant[:RERANK_TOP_N]


def _is_valid_promo(promo: dict) -> bool:
    """Check if a promo has valid pricing data."""
    original = promo.get("original_price")
    promo_price = promo.get("promo_price")

    # Filter out promos with zero or missing original price
    if original is not None and promo_price is not None:
        try:
            orig_float = float(original)
            promo_float = float(promo_price)
            # Bad data: original price is 0 or promo price > original price
            if orig_float <= 0:
                return False
            if promo_float > orig_float:
                return False
        except (ValueError, TypeError):
            pass

    return True


def _pinecone_search_and_rerank(index, query_text: str, filter_dict: dict | None) -> list[dict]:
    """Execute integrated search + rerank in a single Pinecone API call.

    This matches the Pinecone console behavior — the reranker runs server-side
    on the `text` field, producing much higher-quality relevance scores than
    calling pc.inference.rerank() separately.
    """
    logger.info(f"    [search+rerank] query='{query_text}' filter={filter_dict}")

    query = {
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

    hits = []
    try:
        results = index.search_records(namespace="__default__", query=query, rerank=rerank)
        hits = _extract_hits(results)
    except (AttributeError, TypeError):
        try:
            results = index.search(namespace="__default__", query=query, rerank=rerank)
            hits = _extract_hits(results)
        except Exception as e:
            logger.warning(f"    Pinecone search+rerank failed: {e}")
            return []

    # Log and print results
    for h in hits:
        fields = h.get("fields", {})
        logger.info(
            f"      score={h.get('_score', '?'):.4f}  "
            f"{fields.get('normalized_name', '?')} | "
            f"{fields.get('original_description', '?')[:60]}"
        )
    logger.info(f"    [search+rerank] {len(hits)} results returned")

    print(f"\n{'─'*60}")
    print(f"SEARCH+RERANK RESULTS for query: '{query_text}'")
    print(f"{'─'*60}")
    for i, h in enumerate(hits):
        fields = h.get("fields", {})
        status = "KEEP" if h.get("_score", 0) >= RERANK_SCORE_THRESHOLD else "DROP"
        print(f"\n  #{i+1}  score={h.get('_score', '?'):.4f}  [{status}]")
        for k, v in sorted(fields.items()):
            print(f"    {k}: {v}")
    if not hits:
        print("  (no results)")
    print(f"{'─'*60}\n")

    return hits


def _build_promo_dict(fields: dict, score: float) -> dict:
    """Build a clean promo dict from Pinecone fields + relevance score."""
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
    }


def _extract_hits(results) -> list[dict]:
    """Extract hits from Pinecone search response (handles SDK response variations)."""
    # SDK object with .result.hits
    if hasattr(results, "result"):
        result = results.result
        if hasattr(result, "hits"):
            return [_normalize_hit(h) for h in result.hits]

    # Plain dict
    if isinstance(results, dict):
        if "result" in results:
            return [_normalize_hit(h) for h in results["result"].get("hits", [])]
        if "matches" in results:
            return [_normalize_hit(m) for m in results["matches"]]

    # SDK object with .matches (standard query response)
    if hasattr(results, "matches"):
        return [_normalize_hit(m) for m in results.matches]

    return []


def _normalize_hit(hit) -> dict:
    """Normalize a Pinecone hit/match into a consistent dict format."""
    if isinstance(hit, dict):
        # Ensure fields key exists
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
# Step 3: LLM recommendation generation
# ---------------------------------------------------------------------------
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
      "mechanism": "<string: e.g. '1+1 Gratis', '-30%'>",
      "validity_end": "<string: DD/MM>",
      "reason": "<string: one sentence linking deal to user's buying pattern with concrete numbers>"
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
          "mechanism": "<string>"
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
- Respond with ONLY valid JSON. No markdown, no code blocks, no extra text."""


def generate_recommendations(profile: dict, promo_results: dict[str, list[dict]]) -> dict:
    """Send the full user context + matched promos to an LLM for expert analysis.

    Returns a structured dict with keys: weekly_savings, top_picks, stores, smart_switch, summary.
    """
    user_message = _build_llm_context(profile, promo_results)

    raw_response = None
    if GEMINI_API_KEY:
        try:
            raw_response = _call_gemini(user_message)
        except Exception as e:
            logger.warning(f"Gemini failed ({e}), falling back to Anthropic...")
            if ANTHROPIC_API_KEY:
                raw_response = _call_anthropic(user_message)
            else:
                raise
    elif ANTHROPIC_API_KEY:
        raw_response = _call_anthropic(user_message)
    else:
        raise ValueError(
            "No LLM API key available. Set GEMINI_API_KEY or ANTHROPIC_API_KEY in .env"
        )

    return _parse_llm_response(raw_response)


def _call_gemini(user_message: str) -> str:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=GEMINI_API_KEY)
    response = client.models.generate_content(
        model="gemini-3-pro-preview",
        contents=[user_message],
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            max_output_tokens=8192,
            temperature=0.7,
            response_mime_type="application/json",
        ),
    )
    if response.text is None:
        logger.warning(f"Gemini returned None text. Candidates: {response.candidates}")
        if response.candidates:
            for c in response.candidates:
                logger.warning(f"  finish_reason={c.finish_reason}, safety={c.safety_ratings}")
        raise ValueError("Gemini returned empty response — likely blocked by safety filters")
    return response.text


def _call_anthropic(user_message: str) -> str:
    import anthropic

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=8192,
        system=SYSTEM_PROMPT,
        messages=[
            {"role": "user", "content": user_message},
            # Prefill to force JSON output (no markdown wrapping)
            {"role": "assistant", "content": "{"},
        ],
    )
    # Prepend the "{" we used as prefill
    return "{" + response.content[0].text


def _parse_llm_response(raw_response: str) -> dict:
    """Parse and validate the structured JSON response from the LLM.

    Returns a dict with keys: weekly_savings, deal_count, top_picks, stores, smart_switch, summary.
    Falls back to a minimal structure if parsing fails.
    """
    # Strip markdown code fences if the model wrapped the JSON
    clean = raw_response.strip()
    if clean.startswith("```"):
        clean = clean.split("```", 2)[1]
        if clean.startswith("json"):
            clean = clean[4:]
        clean = clean.strip()

    try:
        data = json.loads(clean)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse LLM JSON response: {e}")
        logger.error(f"Raw response (first 500 chars): {raw_response[:500]}")
        return {
            "weekly_savings": 0,
            "deal_count": 0,
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

    # Validate required top-level keys and set defaults
    data.setdefault("weekly_savings", 0)
    data.setdefault("deal_count", 0)
    data.setdefault("top_picks", [])
    data.setdefault("stores", [])
    data.setdefault("smart_switch", None)
    data.setdefault("summary", {})

    # Ensure top_picks is capped at 3
    data["top_picks"] = data["top_picks"][:3]

    # Validate each top pick has required fields
    for pick in data["top_picks"]:
        pick.setdefault("brand", "Unknown")
        pick.setdefault("product_name", "Unknown")
        pick.setdefault("emoji", "🛒")
        pick.setdefault("store", "Unknown")
        pick.setdefault("original_price", 0)
        pick.setdefault("promo_price", 0)
        pick.setdefault("savings", 0)
        pick.setdefault("mechanism", "")
        pick.setdefault("validity_end", "")
        pick.setdefault("reason", "")

    # Validate each store object
    for store in data["stores"]:
        store.setdefault("store_name", "Unknown")
        store.setdefault("store_color", "⬜")
        store.setdefault("total_savings", 0)
        store.setdefault("validity_end", "")
        store.setdefault("items", [])
        store.setdefault("tip", "")
        for item in store["items"]:
            item.setdefault("brand", "Unknown")
            item.setdefault("product_name", "Unknown")
            item.setdefault("emoji", "🛒")
            item.setdefault("original_price", 0)
            item.setdefault("promo_price", 0)
            item.setdefault("savings", 0)
            item.setdefault("mechanism", "")

    # Validate summary
    summary = data["summary"]
    summary.setdefault("total_items", 0)
    summary.setdefault("total_savings", data["weekly_savings"])
    summary.setdefault("stores_breakdown", [])
    summary.setdefault("best_value_store", None)
    summary.setdefault("best_value_savings", 0)
    summary.setdefault("best_value_items", 0)
    summary.setdefault("closing_nudge", "")

    return data


def _build_llm_context(profile: dict, promo_results: dict[str, list[dict]]) -> str:
    """Build structured context for the LLM with profile + promotions."""
    habits = profile["shopping_habits"]
    parts = []

    # ── Section 1: Compact user profile ──
    parts.append("## USER PROFILE")
    parts.append(f"Receipts: {profile['receipts_analyzed']} ({profile['data_period_start']} to {profile['data_period_end']})")
    parts.append(f"Total spend: €{habits.get('total_spend', 0):.2f} | Avg receipt: €{habits.get('avg_receipt_total', 0):.2f} | {habits.get('shopping_frequency_per_week', 0)}x/week")

    # Stores
    stores = habits.get("preferred_stores", [])
    if stores:
        store_lines = [f"  {s['name']}: €{s['spend']:.2f} ({s['pct']}%, {s['visits']} visits)" for s in stores[:5]]
        parts.append("Stores:\n" + "\n".join(store_lines))

    # Health
    if habits.get("avg_health_score") is not None:
        parts.append(f"Health score: {habits['avg_health_score']}/5 | Premium ratio: {habits.get('premium_brand_ratio', 0):.0%}")

    # Health trend (new)
    ht = habits.get("health_trend")
    if ht and ht.get("trend"):
        parts.append(f"Health trend: {ht['trend']} (4w avg: {ht.get('current_4w_avg', '?')} vs prev: {ht.get('previous_4w_avg', '?')})")
        parts.append(f"Fresh produce: {ht.get('fresh_produce_pct', 0)}% of food | Ready meals: {ht.get('ready_meals_pct', 0)}%")

    # Savings (new)
    ss = habits.get("savings_summary")
    if ss:
        parts.append(f"Current savings: €{ss['total_saved']:.2f} total ({ss['savings_rate_pct']}% rate, ~€{ss['monthly_savings_avg']:.2f}/mo)")

    # Brand savings potential (new)
    bsp = habits.get("brand_savings_potential")
    if bsp:
        parts.append(f"Brand split: €{bsp['premium_spend']:.2f} premium / €{bsp['house_brand_spend']:.2f} house brand / €{bsp['unbranded_spend']:.2f} unbranded")
        if bsp['estimated_monthly_savings_if_switch'] > 0:
            parts.append(f"Potential savings switching to house brands: €{bsp['estimated_monthly_savings_if_switch']:.2f}/mo")

    # Indulgence (new)
    ind = habits.get("indulgence_tracker")
    if ind and ind.get("total_indulgence", 0) > 0:
        parts.append(f"Indulgence: €{ind['total_indulgence']:.2f} ({ind['indulgence_pct']}%) — ~€{ind['estimated_yearly']:.0f}/yr")

    # Store loyalty (new)
    sl = habits.get("store_loyalty")
    if sl:
        parts.append(f"Store concentration: {sl['concentration_score']:.2f} HHI | {sl['stores_visited_count']} stores visited")

    # Shopping efficiency (new)
    se = habits.get("shopping_efficiency")
    if se:
        parts.append(f"Small trips (<5 items): {se['small_trips_count']} ({se['small_trips_pct']}%), avg €{se['small_trips_avg_cost']:.2f}")
        if se.get("weekend_premium_pct", 0) != 0:
            parts.append(f"Weekend premium: {se['weekend_premium_pct']:+.1f}% vs weekday")

    # ── Section 2: Interest items with metrics ──
    parts.append("\n## ITEMS TO FIND DEALS FOR")
    parts.append("(Note: null metrics indicate insufficient data for that calculation)")
    for item in profile["promo_interest_items"]:
        name = item.get("normalized_name", "?")
        brands = ", ".join(item.get("brands", [])) or "no brand"
        tags = item.get("tags", [])
        metrics = item.get("metrics", {})
        is_fallback = item.get("is_category_fallback", False)

        # Build metrics string
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

        # Restock urgency indicator
        restock_urgency = metrics.get("restock_urgency")
        urgency_str = ""
        if restock_urgency is not None:
            if restock_urgency >= 1.5:
                urgency_str = " | ⚠️ OVERDUE (urgency {:.1f})".format(restock_urgency)
            elif restock_urgency >= 1.0:
                urgency_str = " | ⏰ DUE NOW (urgency {:.1f})".format(restock_urgency)
            elif restock_urgency >= 0.7:
                urgency_str = " | 📅 due soon (urgency {:.1f})".format(restock_urgency)

        metrics_str = " | ".join(metrics_parts) if metrics_parts else "limited data"
        fallback_str = " [CATEGORY FALLBACK]" if is_fallback else ""

        category = item.get("interest_category", "?")
        tags_str = ", ".join(tags) if tags else "none"
        parts.append(
            f"- **{name}** [{item.get('granular_category', '?')}]{fallback_str}\n"
            f"  brands={brands} | category={category} | tags={tags_str}\n"
            f"  {metrics_str}{urgency_str}"
        )

    # ── Section 3: Matched promotions ──
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

            parts.append(
                f"- {p.get('brand', '?')} · {p.get('original_description', p.get('normalized_name', '?'))}\n"
                f"  €{p.get('original_price', '?')} → €{p.get('promo_price', '?')}{savings_str} | {p.get('promo_mechanism', '?')}\n"
                f"  {p.get('source_retailer', '?')} | {p.get('unit_info') or '?'} | {p.get('validity_start', '?')} to {p.get('validity_end', '?')}"
            )

    parts.append(f"\n**{total_promos} promos matched across {items_with_promos}/{len(promo_results)} items.**")
    parts.append("\nGenerate the weekly promo briefing now.")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    logger.info("=" * 60)
    logger.info("Promo Recommender Testbench")
    logger.info("=" * 60)

    if not PINECONE_API_KEY:
        logger.error("PINECONE_API_KEY not set. Check .env file.")
        sys.exit(1)

    # --- Step 1: Fetch enriched profile ---
    logger.info(f"\nStep 1: Fetching enriched profile for user {USER_ID}...")
    profile = asyncio.run(fetch_enriched_profile(USER_ID))

    interest_items = profile.get("promo_interest_items", [])
    logger.info(f"  Found {len(interest_items)} promo interest items")

    for item in interest_items:
        logger.info(
            f"    - {item['normalized_name']} "
            f"[{item.get('granular_category', 'N/A')}] "
            f"({item.get('interest_category', '?')})"
        )

    if not interest_items:
        logger.warning("No promo interest items found. Exiting.")
        return

    # --- Step 2: Search Pinecone + rerank ---
    logger.info(f"\nStep 2: Searching Pinecone promos index + reranking...")
    pc = Pinecone(api_key=PINECONE_API_KEY)
    index = pc.Index(host=PINECONE_INDEX_HOST)

    all_promo_results: dict[str, list[dict]] = {}
    total_matches = 0

    for item in interest_items:
        name = item["normalized_name"]
        category = item.get("granular_category", "N/A")
        logger.info(f"  Searching: '{name}' (filter: {category})")

        promos = search_promos_for_item(pc, index, item)
        all_promo_results[name] = promos
        total_matches += len(promos)

        if promos:
            scores = [p["relevance_score"] for p in promos]
            logger.info(f"    -> {len(promos)} relevant promos (scores: {scores})")
            for p in promos:
                logger.info(
                    f"      * {p['original_description']} "
                    f"-- {p.get('promo_mechanism') or 'price reduction'}"
                )
        else:
            logger.info(f"    -> No matching promos found")

        # Small delay to avoid rate limits
        time.sleep(0.2)

    logger.info(
        f"\n  Total: {total_matches} relevant promotions "
        f"across {len(interest_items)} items"
    )

    # --- Step 3: Generate LLM recommendations ---
    llm_provider = (
        "Gemini" if GEMINI_API_KEY else "Claude" if ANTHROPIC_API_KEY else "None"
    )
    logger.info(f"\nStep 3: Generating personalized recommendations via {llm_provider}...")

    recommendations = generate_recommendations(profile, all_promo_results)

    # --- Output ---
    print("\n" + "=" * 60)
    print("PERSONALIZED PROMO RECOMMENDATIONS (JSON)")
    print("=" * 60 + "\n")
    print(json.dumps(recommendations, indent=2, ensure_ascii=False))
    print("\n" + "=" * 60)

    # Quick summary
    print(f"\nWeekly savings: €{recommendations.get('weekly_savings', 0):.2f}")
    print(f"Deals found: {recommendations.get('deal_count', 0)}")
    top_picks = recommendations.get("top_picks", [])
    if top_picks:
        print(f"Top picks ({len(top_picks)}):")
        for i, pick in enumerate(top_picks, 1):
            print(f"  {i}. {pick.get('brand', '?')} {pick.get('product_name', '?')} — €{pick.get('promo_price', 0):.2f} (save €{pick.get('savings', 0):.2f}) at {pick.get('store', '?')}")
    stores = recommendations.get("stores", [])
    if stores:
        print(f"Stores ({len(stores)}):")
        for store in stores:
            print(f"  {store.get('store_color', '⬜')} {store.get('store_name', '?')} — {len(store.get('items', []))} items, save €{store.get('total_savings', 0):.2f}")


if __name__ == "__main__":
    main()
