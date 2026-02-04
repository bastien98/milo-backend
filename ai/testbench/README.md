# Promo Recommender Pipeline

## Overview

The promo recommender finds relevant Colruyt promotions for a user based on their shopping history. It works in 3 stages:

1. **Enriched Profile** - Aggregate 90 days of transactions into interest items
2. **Semantic Search + Rerank** - Find matching promos in Pinecone vector DB
3. **LLM Recommendations** - Generate personalized advice via Gemini

## Stage 1: Enriched Profile

The enriched profile (`enriched_profile_service.py`) classifies a user's purchased items into buckets:

| Bucket | Criteria | Max slots |
|--------|----------|-----------|
| `staple` | Bought on >= 0.5 trips/week, >= 3 unique trips | 8 |
| `high_spend` | >= 2 unique trips, sorted by total spend | 6 |
| `brand_loyal` | Dominant brand >= 80% of purchases, >= 2 trips | 4 |
| `health_pick` | Avg health score >= 4, >= 3 trips | 4 |
| `occasional_treat` | Avg health score <= 2, >= 2 trips | 3 |
| `bulk_buy` | Avg >= 2 units/trip, >= 2 trips | 3 |

Items are deduplicated across buckets (first bucket wins). A two-pass allocation guarantees at least 1 item per non-empty bucket before filling remaining slots. Max 25 items total.

Each interest item contains:
- `normalized_name` - clean product name (e.g., "volle melk")
- `brands` - list of brands seen (e.g., ["campina"])
- `granular_category` - product category (e.g., "Milk Fresh")
- `interest_category` - which bucket it was assigned to
- `tags` - frequency/health/brand metadata
- `context` - human-readable purchase summary

## Stage 2: Semantic Search + Rerank

For each interest item, we run a two-step retrieval against the Pinecone promos index.

### Step 2a: Vector Search

Finds candidate promos using embedding similarity (`llama-text-embed-v2` via Pinecone integrated inference).

**Query construction:**

| Bucket | Query format | Example |
|--------|-------------|---------|
| `brand_loyal` | `{Brand} {Name} ({Category})` per brand | `vandemoortele caesar vinaigrette (Salad Dressing)` |
| All others | `{Name} ({Category})` | `volle melk (Milk Fresh)` |

- Category suffix omitted if `granular_category` is `None` or `"Other"`
- Metadata filter: `granular_category = {exact match}` applied first
- If 0 hits with filter, retries without filter (fallback)
- Returns top 20 candidates per search
- For `brand_loyal` with multiple brands, runs one search per brand and deduplicates hits

### Step 2b: Rerank

A cross-encoder (`pinecone-rerank-v0`) scores each candidate against the user's item to judge true relevance.

**Rerank query (what the user is looking for):**

| Bucket | Query | Example |
|--------|-------|---------|
| `brand_loyal` | `{Brand} {Name}` (dominant brand) | `vandemoortele caesar vinaigrette` |
| All others | `{Name}` | `volle melk` |

No category in the rerank query to avoid penalizing promos categorized differently (e.g., user buys "Milk Fresh" but promo is indexed as "Milk Long Life").

**Rerank document (what the promo looks like to the cross-encoder):**

```
{normalized_name}. {original_description}
```

Example:
```
halfvolle melk. Campina volle of halfvolle melk fles of brik 1 L vb.: Halfvolle melk brik
```

- `normalized_name` = clean product name from the promo record (no brand, weight, or category)
- `original_description` = raw Colruyt promo text with all product variants
- Threshold: rerank score >= 0.20 to keep

### Why this split matters

- **Vector search** uses category in the query to steer embeddings toward the right product space. Embeddings handle semantic proximity gracefully ("Milk Fresh" and "Milk Long Life" are close in embedding space).
- **Rerank** strips category to avoid penalizing cross-category matches. The cross-encoder does exact text comparison where a category mismatch could hurt scores.
- **Brand in rerank query** only for `brand_loyal` items, so the cross-encoder prefers brand-specific promos for users who consistently buy a specific brand.

## Stage 3: LLM Recommendations

All matched promos + the user's shopping habits are sent to Gemini 2.0 Flash, which generates:
- Top priority promos (direct matches to staples/high-spend items)
- Smart stock-up opportunities
- Worth-trying suggestions
- Estimated weekly savings

## Running the testbench

```bash
SSL_CERT_FILE=$(python -c "import certifi; print(certifi.where())") python ai/testbench/promo_recommender.py
```

This connects to the production database to fetch the enriched profile and searches the live Pinecone index.
