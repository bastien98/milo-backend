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
    python ai/testbench/promo_recommender.py
"""

import asyncio
import json
import logging
import os
import ssl
import sys
import time
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
BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from dotenv import load_dotenv

load_dotenv(BACKEND_ROOT / ".env")

import asyncpg
from pinecone import Pinecone

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
USER_ID = "c9b6bc31-d05a-4ab4-97fc-f40ff5fe6f67"

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
RERANK_SCORE_THRESHOLD = 0.3  # Min relevance score to keep

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

    For brand_loyal items: runs one search per brand using {Brand} {Name} ({Category}),
    then deduplicates hits across all brand queries before reranking.

    For all other items: searches using {Name} ({Category}).

    Always applies granular_category metadata filter with fallback.
    """
    normalized_name = item["normalized_name"]
    granular_category = item.get("granular_category")
    interest_category = item.get("interest_category")
    brands = item.get("brands", [])

    # Metadata filter
    filter_dict = None
    if granular_category:
        filter_dict = {"granular_category": {"$eq": granular_category}}

    # Build category suffix for query text
    cat_suffix = ""
    if granular_category and granular_category != "Other":
        cat_suffix = f" ({granular_category})"

    # --- Build query texts ---
    if interest_category == "brand_loyal" and brands:
        # One search per brand: {Brand} {Name} ({Category})
        query_texts = [f"{brand} {normalized_name}{cat_suffix}" for brand in brands]
    else:
        # Generic: {Name} ({Category})
        query_texts = [f"{normalized_name}{cat_suffix}"]

    # --- Vector search across all queries ---
    seen_ids: set[str] = set()
    all_hits: list[dict] = []

    for query_text in query_texts:
        hits = _pinecone_search(index, query_text, filter_dict)

        # Fallback without category filter
        if not hits and filter_dict:
            logger.info(f"    No results with category filter for '{query_text}', retrying without filter...")
            hits = _pinecone_search(index, query_text, filter_dict=None)

        # Deduplicate across brand queries
        for hit in hits:
            hit_id = hit.get("_id", "")
            if hit_id and hit_id in seen_ids:
                continue
            if hit_id:
                seen_ids.add(hit_id)
            all_hits.append(hit)

    if not all_hits:
        return []

    # --- Rerank ---
    if interest_category == "brand_loyal" and brands:
        rerank_query = f"{brands[0]} {normalized_name}"
    else:
        rerank_query = normalized_name
    return _rerank_hits(pc, rerank_query, all_hits)


def _pinecone_search(index, query_text: str, filter_dict: dict | None) -> list[dict]:
    """Execute a Pinecone search with integrated embedding, handling SDK variations."""
    logger.info(f"    [vector search] query='{query_text}' filter={filter_dict}")
    query = {
        "inputs": {"text": query_text},
        "top_k": SEARCH_TOP_K,
    }
    if filter_dict:
        query["filter"] = filter_dict

    hits = []
    try:
        results = index.search_records(namespace="__default__", query=query)
        hits = _extract_hits(results)
    except (AttributeError, TypeError):
        try:
            results = index.search(namespace="__default__", query=query)
            hits = _extract_hits(results)
        except Exception as e:
            logger.warning(f"    Pinecone search failed: {e}")
            return []

    for h in hits:
        fields = h.get("fields", {})
        logger.info(
            f"      sim={h.get('_score', '?'):.4f}  "
            f"{fields.get('normalized_name', '?')} | "
            f"{fields.get('original_description', '?')[:60]}"
        )
    logger.info(f"    [vector search] {len(hits)} hits returned")
    return hits


def _rerank_hits(pc: Pinecone, query: str, hits: list[dict]) -> list[dict]:
    """Rerank search hits using Pinecone's reranker and filter by score threshold."""
    # Build documents for the reranker
    documents = []
    for hit in hits:
        fields = hit.get("fields", {})
        name = fields.get("normalized_name", "")
        desc = fields.get("original_description", "")
        documents.append({"id": hit.get("_id", ""), "text": f"{name}. {desc}"})

    logger.info(f"    [rerank] query='{query}' | {len(documents)} docs")
    for i, doc in enumerate(documents):
        logger.info(f"      doc[{i}]: {doc['text'][:80]}")

    try:
        reranked = pc.inference.rerank(
            model="pinecone-rerank-v0",
            query=query,
            documents=documents,
            top_n=RERANK_TOP_N,
            return_documents=True,
        )

        logger.info(f"    [rerank] results:")
        relevant = []
        for result in reranked.data:
            status = "KEEP" if result.score >= RERANK_SCORE_THRESHOLD else "DROP"
            doc_text = result.document.get("text", "")[:60] if result.document else "?"
            logger.info(f"      {status} score={result.score:.4f}  {doc_text}")

            if result.score < RERANK_SCORE_THRESHOLD:
                continue

            original_idx = result.index
            if original_idx < len(hits):
                hit = hits[original_idx]
                fields = hit.get("fields", {})
                relevant.append(_build_promo_dict(fields, result.score))

        return relevant

    except Exception as e:
        logger.warning(f"    Reranking failed ({e}), falling back to vector scores")
        # Fallback: return top N by original vector similarity score
        return [
            _build_promo_dict(hit.get("fields", {}), hit.get("_score", 0))
            for hit in hits[:RERANK_TOP_N]
        ]


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
SYSTEM_PROMPT = """You are an expert shopping analyst and personal promotions advisor for Belgian supermarket shoppers.
You analyze a user's shopping habits and match them with current supermarket promotions to provide highly personalized, actionable recommendations.

CRITICAL RULES — strictly follow these:
- ONLY recommend promotions that are explicitly listed in the provided promotion data. Never invent, guess, or speculate about promotions that might exist.
- Do NOT suggest hypothetical deals (e.g., "watch for Bonus deals", "look out for 1+1 free", "buy X to trigger volume discounts") unless those exact promotions appear in the data.
- If an item has no matching promotions in the data, simply skip it. Do NOT offer strategic advice, speculative savings tips, or suggest potential future deals for items without confirmed active promos.
- Every promotion you mention must be directly traceable to a specific entry in the provided promotion data, with its exact price, mechanism, and validity dates.

Your recommendations should:
1. Prioritize promotions that match the user's regular purchases (staples, high-spend items)
2. Highlight the best savings opportunities based on their actual spending patterns
3. Suggest smart stock-up opportunities for frequently purchased items that have confirmed active promos
4. Note promotions on healthier alternatives if the user has health-conscious picks
5. Calculate estimated savings by combining the user's purchase frequency and spending patterns from their enriched profile with the discount from confirmed promos only (e.g., "you buy this ~2x/week, saving EUR X per unit = ~EUR Y/week")
6. Be specific and actionable — mention exact products, prices, and promo mechanisms as listed in the data
7. Consider the user's preferred stores and shopping frequency
8. Flag any limited-time offers that are expiring soon

Structure your response with:
- Top Priority Promos — biggest impact on their regular spending
- Smart Stock-Up Opportunities — items they buy often that are on promo
- Worth Trying — promotions on items similar to what they buy
- Estimated Weekly Savings — grounded in the user's enriched profile (purchase frequency, quantities) combined with confirmed promo discounts only

If few or no promotions match the user's profile, say so honestly rather than padding the response with speculative suggestions.

Use a friendly but expert tone. Be concise and practical. Respond in English."""


def generate_recommendations(profile: dict, promo_results: dict[str, list[dict]]) -> str:
    """Send the full user context + matched promos to an LLM for expert analysis."""
    user_message = _build_llm_context(profile, promo_results)

    if GEMINI_API_KEY:
        return _call_gemini(user_message)
    elif ANTHROPIC_API_KEY:
        return _call_anthropic(user_message)
    else:
        raise ValueError(
            "No LLM API key available. Set GEMINI_API_KEY or ANTHROPIC_API_KEY in .env"
        )


def _call_gemini(user_message: str) -> str:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=GEMINI_API_KEY)
    response = client.models.generate_content(
        model="gemini-3-pro-preview",
        contents=[user_message],
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            max_output_tokens=4096,
            temperature=0.7,
        ),
    )
    return response.text


def _call_anthropic(user_message: str) -> str:
    import anthropic

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )
    return response.content[0].text


def _build_llm_context(profile: dict, promo_results: dict[str, list[dict]]) -> str:
    """Build the full context message for the LLM with profile + promotions."""
    parts = []

    parts.append("## User Shopping Profile\n")
    parts.append("### Shopping Habits")
    parts.append(json.dumps(profile["shopping_habits"], indent=2, default=str))

    parts.append("\n### Promo Interest Items (ranked by relevance)")
    parts.append(json.dumps(profile["promo_interest_items"], indent=2, default=str))

    parts.append(f"\n### Data Period")
    parts.append(
        f"Based on {profile['receipts_analyzed']} receipts from "
        f"{profile['data_period_start']} to {profile['data_period_end']}"
    )

    parts.append("\n\n## Matching Current Promotions\n")

    items_with_promos = 0
    total_promos = 0

    for item_name, promos in promo_results.items():
        parts.append(f"### {item_name}")
        if promos:
            items_with_promos += 1
            for p in promos:
                total_promos += 1
                price_info = ""
                if p.get("original_price") and p.get("promo_price"):
                    try:
                        savings = float(p["original_price"]) - float(p["promo_price"])
                        price_info = (
                            f"EUR {p['original_price']} -> EUR {p['promo_price']} "
                            f"(save EUR {savings:.2f})"
                        )
                    except (ValueError, TypeError):
                        price_info = (
                            f"EUR {p.get('original_price', '?')} -> "
                            f"EUR {p.get('promo_price', '?')}"
                        )
                elif p.get("promo_price"):
                    price_info = f"EUR {p['promo_price']}"

                parts.append(
                    f"- **{p.get('original_description', p.get('normalized_name', '?'))}**"
                )
                if price_info:
                    parts.append(f"  Price: {price_info}")
                if p.get("promo_mechanism"):
                    parts.append(f"  Promo: {p['promo_mechanism']}")
                parts.append(
                    f"  Category: {p.get('granular_category', 'N/A')} | "
                    f"Brand: {p.get('brand', 'N/A')} | "
                    f"Valid: {p.get('validity_start', '?')} to {p.get('validity_end', '?')}"
                )
                parts.append(f"  Relevance score: {p.get('relevance_score', 'N/A')}")
        else:
            parts.append("- No matching promotions found currently")
        parts.append("")

    parts.append(
        f"\n**Summary:** {total_promos} matching promos found across "
        f"{items_with_promos}/{len(promo_results)} interest items."
    )

    parts.append(
        "\n\nAnalyze this user's profile and the matching promotions above. "
        "Provide personalized, actionable recommendations."
    )

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
    print("PERSONALIZED PROMO RECOMMENDATIONS")
    print("=" * 60 + "\n")
    print(recommendations)
    print("\n" + "=" * 60)


if __name__ == "__main__":
    main()
