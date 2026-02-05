# Promo Recommender Pipeline

## Overview

The promo recommender finds relevant supermarket promotions for a user based on their shopping history. It works in 3 stages:

1. **Enriched Profile** - Aggregate 90 days of transactions into interest items
2. **Semantic Search + Rerank** - Find matching promos in Pinecone vector DB
3. **LLM Recommendations** - Generate personalized advice via LLM

### Models used

| Stage | Model | Purpose |
|-------|-------|---------|
| Vector search (embedding) | `llama-text-embed-v2` | Pinecone integrated inference for semantic similarity |
| Rerank (cross-encoder) | `bge-reranker-v2-m3` | Pinecone integrated rerank to score true relevance |
| LLM | Gemini 3 Pro Preview / Claude Sonnet 4 | Generate personalized recommendations (first available key wins) |

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

Search and rerank run as a single integrated Pinecone API call. The cross-encoder (`bge-reranker-v2-m3`) re-scores each vector search candidate against the query to judge true relevance.

**Rerank field:** `text` — the structured embedding text stored on each Pinecone record, e.g.:

```
pringles chips 165g (Chips)
lay's chips oven baked naturel 150 g (Chips)
```

This field contains `{brand} {normalized_name} {unit_info} ({category})` and gives the cross-encoder a concise, consistent representation to compare against the query.

**Rerank query:** same as the vector search query (see table above).

- Threshold: rerank score >= 0.55 to keep
- Top N: 5 results max per interest item

**Note on model choice:** `bge-reranker-v2-m3` produces well-calibrated scores (genuine matches score 0.5–0.9, irrelevant items score <0.05). The alternative `pinecone-rerank-v0` scores an order of magnitude lower on the same data (~0.04–0.06 for relevant matches), making threshold tuning impractical.

## Stage 3: LLM Recommendations

All matched promos + the user's shopping habits are sent to an LLM (Gemini 3 Pro Preview or Claude Sonnet 4, whichever API key is available), which generates:
- Top priority promos (direct matches to staples/high-spend items)
- Smart stock-up opportunities
- Worth-trying suggestions
- Estimated weekly savings

## Running the testbench

```bash
SSL_CERT_FILE=$(python -c "import certifi; print(certifi.where())") python ai/testbench/promo_recommender.py
```

This connects to the production database to fetch the enriched profile and searches the live Pinecone index.
