# Promo Recommendation Research: Receipt-Based Personalization for Grocery Retail

## Executive Summary

This document covers how the supermarket/retail industry recommends promotions based on purchase history from receipts. It maps industry best practices to what Milo already does and identifies practical improvements achievable with PostgreSQL + Python at a small panel scale (thousands of users).

---

## 1. Common Recommendation Approaches Used by Retailers

### 1a. Rule-Based / Heuristic Targeting (simplest, most common at small scale)

The oldest and most proven approach. Catalina Marketing pioneered this in the 1990s with checkout printers that issued coupons based on UPC scan data. The logic is straightforward:

- **Bought X, recommend X again** (replenishment): User bought diapers 3 weeks ago, avg cycle is 4 weeks, show diaper promos now
- **Bought X, recommend Y** (cross-sell): User buys pasta frequently, recommend pasta sauce promos
- **Bought competitor X, recommend brand Y** (conquest): User buys Coca-Cola, show Pepsi promo at a discount
- **Category affinity**: User spends heavily on "Snacks & Sweets", surface all promos in that parent category

**Why it works at small scale**: No minimum user count needed. Works with a single user's history. This is essentially what Milo already does via `_build_promo_interest_items()`.

### 1b. Content-Based Filtering

Matches promo attributes (category, brand, price range) against user preference profiles derived from purchase history:

- Build a user profile vector from categories/brands purchased (weighted by frequency/recency)
- Score each available promo by similarity to the user profile
- No need for other users' data -- works in complete isolation

**Milo's current approach is largely content-based**: enriched profile builds category breakdowns, brand preferences, and granular category lists, then searches Pinecone using semantic similarity on product names.

### 1c. Collaborative Filtering (CF)

The insight: "users who bought similar things in the past will want similar things in the future."

- **User-based CF**: Find users with similar purchase patterns, recommend promos they engaged with that the current user hasn't seen
- **Item-based CF**: Find items frequently co-purchased, recommend promos for co-occurring items
- **Matrix factorization**: Decompose the user-item interaction matrix into latent factors

**Scale requirement**: CF needs sufficient user overlap. With thousands of users (not millions), user-based CF is sparse. **Item-based CF and co-purchase analysis are much more viable at small scale** because item-item relationships are denser than user-user relationships.

### 1d. Hybrid Approaches

Every major retailer uses hybrids. dunnhumby (Tesco Clubcard) combines:
- Customer segmentation (lifestyle clusters from purchase data)
- Category-level targeting (which categories the user over/under-indexes in)
- Brand loyalty/switching signals
- Promotional responsiveness scoring (does this user actually respond to promos?)

84.51 (Kroger) uses:
- Predictive ML on thousands of customer attributes from loyalty card data
- "Forgot something" algorithms based on real-time basket composition
- Personalized pricing based on individual price elasticity

**For Milo's scale**: A hybrid of rule-based (current approach) + item co-purchase analysis + category affinity scoring is the sweet spot.

---

## 2. How Major Players Use Receipt/Purchase Data

### 2a. dunnhumby / Tesco Clubcard

- **Scale**: 24 million Clubcard households in the UK
- **Core innovation**: By 1997, personalized coupons were down to 1-to-1 level via deep customer segmentation
- **Approach**: Segment customers into lifestyle clusters, then target promotions by segment. Key dimensions: category spend share, brand preference within category, deal sensitivity, shopping mission type
- **Key lesson for Milo**: dunnhumby's earliest success came from relatively simple segmentation (not deep ML). They grouped customers by what % of their basket goes to each department and which brands they prefer. This is achievable with receipt data alone.

### 2b. Catalina Marketing

- **Approach**: Real-time, UPC-triggered promotions at checkout
- **Core logic**: When a consumer buys product X, issue a coupon for X (retention) or competitor Y (conquest)
- **Targeting rules**: Brand loyalty detection (consistently buys brand A), category switcher detection (alternates between brands), lapsed buyer detection (used to buy X, stopped)
- **Key lesson for Milo**: Catalina proves that simple rule-based targeting ("bought X, recommend Y") delivers measurable ROI. The sophistication is in the rules, not the algorithm.

### 2c. Kroger / 84.51

- **Scale**: 62 million US households via Kroger Plus loyalty
- **Approach**: Predictive + prescriptive ML processing thousands of first-party attributes
- **Features used**: Day of week, basket size, modality (online/in-store), seasonality, brand affinity, price sensitivity
- **Key innovation**: "Forgot something" algorithm -- predicts what the user is making (recipe detection from basket) and suggests missing ingredients
- **Key lesson for Milo**: Even Kroger started with simpler approaches. The "forgot something" pattern maps to co-purchase analysis, which Milo could implement with SQL.

### 2d. Ibotta

- **Approach**: Receipt-scanning app (closest analog to Milo's consumer flow)
- **Targeting**: Personalizes cashback offers based on past purchases, with offers that evolve as usage patterns develop
- **Cold start**: New users get higher-value generic offers; as history builds, offers become more targeted and potentially lower-value
- **Key lesson for Milo**: Ibotta shows that receipt-scanning apps can personalize effectively. Their progression from generic to personalized as history builds is a model Milo should follow.

---

## 3. Key Signals from Purchase Data That Drive Promo Relevance

### 3a. Purchase Frequency per Category/Brand

**What Milo already computes** (in `enriched_profile_service.py`):
- `purchase_frequency_days` (avg gap between purchases per item)
- `trip_count` per item
- `freq_per_week` classification (weekly, biweekly)
- `top_granular_categories` (top 15 by count)

**What the industry adds**:
- **Category purchase cycle**: Different categories have natural replenishment cycles (milk = weekly, detergent = monthly, olive oil = every 2 months). Detecting when a user is "due" for a category repurchase is the #1 signal for promo timing.
- **Share of requirements**: What % of a user's total category spend happens at each store? If a user buys 80% of their dairy at Colruyt but only 20% at Delhaize, a Delhaize dairy promo might convince them to shift share.

**Milo already has `restock_urgency`** (days_since / avg_gap) which is exactly this signal. This is well implemented.

### 3b. Brand Loyalty vs. Switching Behavior

**What Milo already computes**:
- `CATEGORY_BRAND_LOYAL_THRESHOLD = 0.65` -- if top brand holds >= 65% of category purchases, classify as brand_loyal
- `interest_category` tags: "brand_loyal" vs "price_switcher"
- Category-level brand concentration analysis

**What the industry adds**:
- **Brand switching matrices**: dunnhumby tracks "from brand A to brand B" transitions over time. This is exactly what Milo's data platform already computes in `mart_brand_switching`.
- **Promotional responsiveness**: Does the user actually switch brands when shown a promo? Track whether promo views lead to purchase changes. This requires promo event tracking (which Milo already has via `PromoReportEvent`).
- **Loyalty tiers within category**: Not just loyal/switcher binary, but a spectrum: hardcore loyal (>90% one brand), soft loyal (60-80%), variety seeker (no brand >40%), deal-driven switcher (buys whatever is cheapest)

### 3c. Price Sensitivity Indicators

**What Milo already computes**:
- `premium_brand_ratio` -- ratio of premium to non-premium items
- `brand_savings_potential` -- estimated savings if switching from premium to house brands
- `savings_summary` -- total saved from discounts, savings rate per store

**What the industry adds**:
- **Price elasticity per category**: Track whether the user buys more of a category when prices drop. If user's yoghurt purchases spike during promos, they're price-elastic in yoghurt.
- **Deal depth sensitivity**: Some users only respond to deep discounts (>30%), others respond to any discount. Track minimum discount threshold that triggers a purchase change.
- **Upward/downward trading**: Is the user gradually buying more premium or more budget products over time? Trend in avg unit price per category.

### 3d. Basket Composition Patterns

**What Milo already computes**:
- `typical_basket_size`
- `category_breakdown` with spend percentages
- `shopping_efficiency` (small trips vs big shops)

**What the industry adds**:
- **Co-purchase affinity** (market basket analysis): Which products appear together in the same receipt? If pasta and parmesan frequently co-occur, a pasta promo should also surface parmesan promos. This is SQL-computable.
- **Shopping mission detection**: Is this a "stock-up" trip (large basket, many categories) or a "top-up" trip (few items, specific category)? Different promo strategies for each.
- **Complementary vs. substitute items**: Distinguish between items bought together (complementary -- cross-sell) and items that replace each other (substitutes -- conquest offers).

### 3e. Recency/Frequency/Monetary (RFM) Analysis

**What Milo partially computes**:
- Recency: `days_since_last_purchase` per item
- Frequency: `trip_count`, `purchase_frequency_days`
- Monetary: `total_spend` per item, `avg_unit_price`

**What a full RFM implementation adds**:
- **RFM scoring per category**: Score users 1-5 on R, F, M within each category. A user scoring 5-5-5 in "Beer" is a high-value beer buyer who should see beer promos prominently.
- **RFM decay**: Recalculate quarterly with time-decay weighting (recent purchases count more). Milo's 120-day lookback window already provides this naturally.
- **Segment-based targeting**: RFM segments map to promo strategies:
  - Champions (5-5-5): Show premium/new products, upsell
  - Loyal (X-4+-X): Show loyalty rewards, early access
  - At risk (1-X-X): Win-back promos, deeper discounts
  - New (5-1-X): Nurture with category-expanding promos

---

## 4. Practical PostgreSQL-Friendly Approaches (No Vector DB Required)

### 4a. Category Affinity Scoring (SQL)

Compute a score per user per category based on purchase history:

```sql
-- Category affinity score: combines frequency, recency, and spend share
WITH user_category_stats AS (
    SELECT
        user_id,
        category,
        COUNT(*) AS purchase_count,
        SUM(item_price) AS total_spend,
        MAX(date) AS last_purchase_date,
        -- Time-decay: weight recent purchases more heavily
        SUM(
            item_price * EXP(-0.02 * EXTRACT(DAY FROM NOW() - date))
        ) AS decay_weighted_spend
    FROM transactions
    WHERE NOT is_discount AND NOT is_deposit
      AND date >= NOW() - INTERVAL '120 days'
    GROUP BY user_id, category
),
user_totals AS (
    SELECT user_id, SUM(total_spend) AS total_user_spend
    FROM user_category_stats
    GROUP BY user_id
)
SELECT
    s.user_id,
    s.category,
    s.purchase_count,
    s.total_spend,
    ROUND(s.total_spend / NULLIF(t.total_user_spend, 0) * 100, 1) AS spend_share_pct,
    EXTRACT(DAY FROM NOW() - s.last_purchase_date) AS days_since_last,
    s.decay_weighted_spend,
    -- Composite affinity score (0-100)
    ROUND(
        (0.4 * (s.decay_weighted_spend / NULLIF(t.total_user_spend, 0) * 100)) +
        (0.3 * LEAST(s.purchase_count, 20) * 5) +
        (0.3 * GREATEST(0, 100 - EXTRACT(DAY FROM NOW() - s.last_purchase_date)))
    , 1) AS affinity_score
FROM user_category_stats s
JOIN user_totals t USING (user_id)
ORDER BY s.user_id, affinity_score DESC;
```

**How to use**: Match promos to users where `promo.category` matches user's top-N affinity categories. Already partially implemented in Milo via `top_granular_categories`.

### 4b. Brand Preference Matching (SQL)

```sql
-- Brand preference within each granular category
WITH brand_purchases AS (
    SELECT
        user_id,
        granular_category,
        normalized_brand,
        COUNT(*) AS times_bought,
        SUM(item_price) AS brand_spend,
        MAX(date) AS last_bought
    FROM transactions
    WHERE normalized_brand IS NOT NULL
      AND NOT is_discount AND NOT is_deposit
      AND date >= NOW() - INTERVAL '120 days'
    GROUP BY user_id, granular_category, normalized_brand
),
category_totals AS (
    SELECT user_id, granular_category, SUM(times_bought) AS total_purchases
    FROM brand_purchases
    GROUP BY user_id, granular_category
)
SELECT
    bp.user_id,
    bp.granular_category,
    bp.normalized_brand,
    bp.times_bought,
    ROUND(bp.times_bought::numeric / ct.total_purchases * 100, 1) AS brand_share_pct,
    CASE
        WHEN bp.times_bought::numeric / ct.total_purchases >= 0.80 THEN 'hardcore_loyal'
        WHEN bp.times_bought::numeric / ct.total_purchases >= 0.60 THEN 'soft_loyal'
        WHEN bp.times_bought::numeric / ct.total_purchases >= 0.30 THEN 'variety_seeker'
        ELSE 'deal_driven'
    END AS loyalty_tier
FROM brand_purchases bp
JOIN category_totals ct USING (user_id, granular_category)
WHERE ct.total_purchases >= 3  -- minimum purchases for meaningful signal
ORDER BY bp.user_id, bp.granular_category, bp.times_bought DESC;
```

**Promo strategy by loyalty tier**:
- `hardcore_loyal`: Show promos for THEIR preferred brand (retention)
- `soft_loyal`: Show both their brand and competitive offers
- `variety_seeker`: Show best deals across all brands in category
- `deal_driven`: Show deepest discount regardless of brand

### 4c. Co-Purchase Analysis (Market Basket Rules via SQL)

```sql
-- Find products frequently bought together (same receipt)
-- This is "item-item collaborative filtering" without the ML
WITH receipt_items AS (
    SELECT DISTINCT receipt_id, granular_category
    FROM transactions
    WHERE NOT is_discount AND NOT is_deposit
      AND granular_category IS NOT NULL
      AND granular_category != 'Other'
),
category_pairs AS (
    SELECT
        a.granular_category AS category_a,
        b.granular_category AS category_b,
        COUNT(DISTINCT a.receipt_id) AS co_occurrence_count
    FROM receipt_items a
    JOIN receipt_items b ON a.receipt_id = b.receipt_id
        AND a.granular_category < b.granular_category  -- avoid duplicates
    GROUP BY a.granular_category, b.granular_category
),
category_counts AS (
    SELECT granular_category, COUNT(DISTINCT receipt_id) AS total_receipts
    FROM receipt_items
    GROUP BY granular_category
)
SELECT
    cp.category_a,
    cp.category_b,
    cp.co_occurrence_count,
    -- Support: how often do A and B appear together?
    ROUND(cp.co_occurrence_count::numeric /
        (SELECT COUNT(DISTINCT receipt_id) FROM receipt_items) * 100, 2) AS support_pct,
    -- Confidence: given A, how likely is B?
    ROUND(cp.co_occurrence_count::numeric / ca.total_receipts * 100, 2) AS confidence_a_to_b,
    -- Lift: is co-occurrence above random chance?
    ROUND(
        (cp.co_occurrence_count::numeric * (SELECT COUNT(DISTINCT receipt_id) FROM receipt_items))
        / (ca.total_receipts * cb.total_receipts)
    , 2) AS lift
FROM category_pairs cp
JOIN category_counts ca ON ca.granular_category = cp.category_a
JOIN category_counts cb ON cb.granular_category = cp.category_b
WHERE cp.co_occurrence_count >= 5  -- minimum support
ORDER BY lift DESC;
```

**How to use**: If user just bought items in category A, also show promos for categories with high lift scores paired with A. Store the top co-purchase pairs in a lookup table, refresh weekly.

### 4d. Simple Collaborative Filtering via SQL (User Similarity)

```sql
-- Find similar users based on category purchase overlap (Jaccard similarity)
WITH user_categories AS (
    SELECT DISTINCT user_id, granular_category
    FROM transactions
    WHERE NOT is_discount AND NOT is_deposit
      AND granular_category IS NOT NULL
      AND date >= NOW() - INTERVAL '90 days'
),
user_pairs AS (
    SELECT
        a.user_id AS user_a,
        b.user_id AS user_b,
        COUNT(*) AS shared_categories
    FROM user_categories a
    JOIN user_categories b ON a.granular_category = b.granular_category
        AND a.user_id < b.user_id
    GROUP BY a.user_id, b.user_id
),
user_category_counts AS (
    SELECT user_id, COUNT(*) AS category_count
    FROM user_categories
    GROUP BY user_id
)
SELECT
    up.user_a,
    up.user_b,
    up.shared_categories,
    -- Jaccard similarity: intersection / union
    ROUND(
        up.shared_categories::numeric /
        (ca.category_count + cb.category_count - up.shared_categories)
    , 3) AS jaccard_similarity
FROM user_pairs up
JOIN user_category_counts ca ON ca.user_id = up.user_a
JOIN user_category_counts cb ON cb.user_id = up.user_b
WHERE up.shared_categories >= 3
ORDER BY jaccard_similarity DESC;
```

**How to use**: For user X, find top-5 similar users, then look at what categories/brands those users buy that user X doesn't. Surface promos for those "discovery" categories. Refresh the similarity matrix weekly as a batch job.

**Caveat**: With thousands of users, the pair-wise comparison is O(n^2) but still manageable -- 5,000 users = 12.5M pairs, which PostgreSQL handles fine as a batch job.

### 4e. Time-Decay Weighted Purchase History

The exponential decay function is the industry standard:

```python
import math
from datetime import date

def time_decay_weight(purchase_date: date, half_life_days: int = 30) -> float:
    """Exponential decay weight. Half-life = days until weight halves.

    - Purchase today: weight = 1.0
    - Purchase 30 days ago (with half_life=30): weight = 0.5
    - Purchase 60 days ago: weight = 0.25
    - Purchase 120 days ago: weight = 0.0625
    """
    days_ago = (date.today() - purchase_date).days
    decay_rate = math.log(2) / half_life_days
    return math.exp(-decay_rate * days_ago)
```

**Application**: Replace simple count-based signals with decay-weighted counts:
- Instead of "bought beer 10 times in 120 days" -> "decay-weighted beer score = 6.2 (recent purchases count more)"
- A user who bought beer 8 times last month is more promo-ready than one who bought 12 times but stopped 2 months ago

**SQL version**:
```sql
SUM(EXP(-0.023 * EXTRACT(DAY FROM NOW() - date))) AS decay_weighted_frequency
-- 0.023 = ln(2)/30 for 30-day half-life
```

### 4f. Rule-Based Cross-Sell Targeting

Pre-compute and store a "bought X -> recommend Y" rules table:

```sql
-- Materialized view refreshed weekly
CREATE MATERIALIZED VIEW promo_cross_sell_rules AS
WITH ... (co-purchase analysis from 4c above)
SELECT
    category_a AS trigger_category,
    category_b AS recommend_category,
    confidence_a_to_b,
    lift
WHERE lift > 1.5 AND confidence_a_to_b > 20
ORDER BY lift DESC;
```

Then at candidate generation time:
1. Look at user's recent purchases (last 2 weeks)
2. For each category purchased, look up cross-sell rules
3. Add promos from `recommend_category` to the candidate pool

---

## 5. What Works Best for a Small Panel (Thousands of Users)

### 5a. Recommended Priority Order for Milo

Given Milo's current state (enriched profiles, Pinecone vector search, ~thousands of users), here is the priority order:

**Tier 1 -- Already working, optimize** (ROI: high, effort: low):
1. **Restock-based targeting** (already implemented via `restock_urgency`). This is the #1 signal at any scale. Refine the timing model.
2. **Category affinity** (already implemented via `top_granular_categories`). Weight by time-decay rather than simple counts.
3. **Brand loyalty classification** (already implemented via `interest_category`). Expand from binary (loyal/switcher) to 4-tier spectrum.

**Tier 2 -- High value additions** (ROI: high, effort: medium):
4. **Co-purchase rules** (market basket analysis). Run as a weekly batch SQL job. Store a `category_co_purchase_rules` table. Use it to expand the candidate pool beyond direct matches.
5. **Time-decay weighting** on all signals. Replace simple counts/averages with exponentially decayed versions. This makes recommendations more responsive to changing habits.
6. **Promotional responsiveness tracking**. Use existing `PromoReportEvent` data to detect which users actually engage with promos. Down-weight/up-weight promo aggressiveness accordingly.

**Tier 3 -- Valuable but needs more data** (ROI: medium, effort: medium):
7. **User-user similarity** (Jaccard on categories). With 1,000+ active users, this becomes meaningful. Use it for "discovery" promos (categories the user hasn't tried but similar users buy).
8. **Category-store affinity**. Already computed in `store_loyalty.category_store_map`. Use this to prioritize promos from stores where the user DOESN'T currently shop for a category (market share capture).
9. **Price sensitivity scoring per category**. Track whether a user's purchase frequency in a category increases during promo weeks.

**Tier 4 -- Future/scale-dependent** (ROI: uncertain, effort: high):
10. **Collaborative filtering with matrix factorization**. Needs thousands of active users minimum. Not worth implementing until user base grows significantly.
11. **Real-time basket completion** (Kroger's "forgot something"). Requires real-time purchase data during a shopping session, which receipt scanning doesn't provide.
12. **Deep learning recommendation models**. Overkill for current scale. Simple SQL-based approaches will outperform until you have 50k+ users.

### 5b. Why Simple Beats Complex at Small Scale

Research on grocery recommendation systems consistently finds:

1. **Popularity baselines are surprisingly hard to beat** at small scale. "Show the user promos for products they already buy frequently" beats most ML approaches when you have limited data per user.

2. **Item-based approaches > user-based** at small scale. With thousands of users, user-user similarity is sparse. But item-item co-purchase patterns are dense (every receipt provides pairs).

3. **Domain rules add massive value**. Grocery has strong priors: people replenish staples on cycles, certain categories always co-occur (bread + butter, pasta + sauce), seasonal products spike predictably. Encoding these as rules costs nothing and works immediately.

4. **Cold start is the real problem**. New users with 0-2 receipts get terrible recommendations from any algorithm. The best approach (which Milo already partially implements with `category_fallback`) is: start with popular items in the user's preferred stores, then personalize progressively as data accumulates. The threshold is approximately 5-8 receipts before personalization meaningfully outperforms popularity.

### 5c. Recommended Data Architecture

```
Transaction data (PostgreSQL)
        |
        v
Weekly batch job (Python/SQL):
  1. Rebuild enriched profiles (already exists)
  2. Compute category affinity scores (new)
  3. Compute co-purchase rules (new)
  4. Compute user similarity matrix (new, deferred)
  5. Score promos against user profiles (replaces/supplements Pinecone)
        |
        v
promo_candidates table (already exists)
  - candidates_json includes scored promos per user
        |
        v
Serve-time assembly (already exists)
  - Filter by preferred_stores
  - Sort by composite score
  - Return to app
```

The key insight: **most of the personalization should happen in the weekly batch job, not at serve time**. This is exactly what Milo's architecture already does with `PromoCandidateGenerationService`. The improvement path is enriching the signals that feed into candidate generation.

---

## 6. What Milo Already Does Well vs. Gaps

### Already Strong:
- Enriched profile with 120-day lookback window
- Interest item classification (staple, top_purchase, brand_loyal, price_switcher, bulk_buy, tried_recently)
- Restock urgency scoring
- Semantic search via Pinecone for matching interest items to promos
- Brand-aware search (brand-loyal items include brand in query, others strip it)
- Category fallback for users with sparse data
- Pre-computed candidates with serve-time assembly (scalable architecture)

### Gaps to Fill:
1. **No co-purchase expansion**: Currently only searches for items the user has bought. Should also search for complementary items (e.g., user buys lots of pasta -> also show parmesan promos).
2. **No time-decay on signals**: All purchases in the 120-day window are weighted equally. Recent purchases should count more.
3. **No promotional responsiveness tracking**: Events are logged but not fed back into scoring. Users who never engage with promos should get fewer/different promos.
4. **Binary brand loyalty**: Only "loyal" vs "switcher". A 4-tier model would enable more nuanced targeting.
5. **No user-user discovery**: All recommendations are based on the individual's history. Similar users' preferences could expand the candidate pool.
6. **No discount depth optimization**: All promos scored equally regardless of discount %. Price-sensitive users should see deeper discounts first.

---

## Sources

- [dunnhumby Wikipedia](https://en.wikipedia.org/wiki/Dunnhumby)
- [Clubcard at 30 - Computer Weekly](https://www.computerweekly.com/feature/Clubcard-at-30-the-evolution-of-retail-loyalty)
- [Tesco Media Platform - dunnhumby](https://www.dunnhumby.com/tesco-media-insight-platform/)
- [Catalina Marketing - Encyclopedia.com](https://www.encyclopedia.com/books/politics-and-business-magazines/catalina-marketing-corporation)
- [Catalina Marketing](https://www.catalina.com/)
- [84.51 - How Data Science Enables Personalization](https://www.8451.com/knowledge-hub/technology/how-data-science-enables-the-personalized-experience-customers-crave/)
- [Kroger Personalized Deals - Grocery Coupon Guide](https://www.grocerycouponguide.com/articles/shoppers-say-krogers-loyalty-app-is-offering-more-personalized-deals/)
- [84.51 with Databricks](https://www.databricks.com/customers/8451)
- [RecDB PostgreSQL Recommendation Engine](https://github.com/DataSystemsLab/recdb-postgresql)
- [Online Grocery Recommender Systems - ScienceDirect](https://www.sciencedirect.com/science/article/pii/S0747563224002048)
- [Building a Recommendation Engine with PostgreSQL - Reintech](https://reintech.io/blog/building-recommendation-engine-postgresql)
- [Market Basket Analysis with SQL](https://vthcong.github.io/MBA.html)
- [RFM Analysis - Mailchimp](https://mailchimp.com/resources/rfm-analysis/)
- [RFM Segmentation - Optimove](https://www.optimove.com/resources/learning-center/rfm-segmentation)
- [Personalization of Supermarket Product Recommendations - ResearchGate](https://www.researchgate.net/publication/280483409_Personalization_of_Supermarket_Product_Recommendations)
- [Grocery Personalization - Mercatus](https://www.mercatus.com/blog/the-promise-of-personalization-realized/)
