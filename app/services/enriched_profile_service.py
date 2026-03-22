import logging
from collections import Counter, defaultdict
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import invalidate_user
from app.models.transaction import Transaction
from app.models.receipt import Receipt
from app.models.enums import ReceiptStatus
from app.db.repositories.enriched_profile_repo import EnrichedProfileRepository

logger = logging.getLogger(__name__)

# How many days of history to aggregate
LOOKBACK_DAYS = 120
# Max promo interest items
MAX_INTEREST_ITEMS = 25
# Category-level brand loyalty: if top brand holds >= this share of purchases
# within a granular_category, items are classified brand_loyal; otherwise price_switcher.
CATEGORY_BRAND_LOYAL_THRESHOLD = 0.65
CATEGORY_BRAND_MIN_PURCHASES = 3


class EnrichedProfileService:

    @staticmethod
    async def rebuild_profile(user_id: str, db: AsyncSession) -> None:
        """Rebuild the enriched profile for a user from last 3 months of data."""
        try:
            cutoff = date.today() - timedelta(days=LOOKBACK_DAYS)

            # Fetch all transactions in the window
            result = await db.execute(
                select(Transaction).where(
                    and_(
                        Transaction.user_id == user_id,
                        Transaction.date >= cutoff,
                    )
                )
            )
            transactions = list(result.scalars().all())

            # Count receipts in the window
            receipt_count_result = await db.execute(
                select(func.count(Receipt.id)).where(
                    and_(
                        Receipt.user_id == user_id,
                        Receipt.receipt_date >= cutoff,
                        Receipt.status == ReceiptStatus.COMPLETED,
                    )
                )
            )
            receipt_count = receipt_count_result.scalar() or 0

            # Fetch receipts for receipt-level aggregations (time_of_day, payment_insights)
            receipt_result = await db.execute(
                select(Receipt).where(
                    and_(
                        Receipt.user_id == user_id,
                        Receipt.receipt_date >= cutoff,
                        Receipt.status == ReceiptStatus.COMPLETED,
                    )
                )
            )
            receipts = list(receipt_result.scalars().all())

            # Build aggregated data
            shopping_habits = _build_shopping_habits(transactions, receipt_count, cutoff, receipts)
            promo_items = _build_promo_interest_items(transactions, cutoff)

            # Determine actual date range from data
            if transactions:
                period_start = min(t.date for t in transactions)
                period_end = max(t.date for t in transactions)
            else:
                period_start = cutoff
                period_end = date.today()

            # Upsert
            repo = EnrichedProfileRepository(db)
            await repo.upsert(
                user_id=user_id,
                shopping_habits=shopping_habits,
                promo_interest_items=promo_items,
                data_period_start=period_start,
                data_period_end=period_end,
                receipts_analyzed=receipt_count,
            )

            # Invalidate analytics/budget cache since transaction data has changed
            invalidate_user(user_id)

            logger.info(
                f"Enriched profile rebuilt for user {user_id}: "
                f"{receipt_count} receipts, {len(transactions)} transactions, "
                f"{len(promo_items)} interest items"
            )
        except Exception:
            logger.exception(f"Failed to rebuild enriched profile for user {user_id}")


def _build_shopping_habits(
    transactions: list[Transaction],
    receipt_count: int,
    cutoff: date,
    receipts: list | None = None,
) -> dict[str, Any]:
    """Aggregate transaction data into a shopping habits summary."""
    if not transactions:
        return {
            "total_spend": 0,
            "receipt_count": 0,
            "avg_receipt_total": 0,
            "shopping_frequency_per_week": 0,
            "preferred_stores": [],
            "category_breakdown": [],
            "premium_brand_ratio": 0,
            "top_granular_categories": [],
            "typical_basket_size": 0,
            "savings_summary": None,
            "shopping_efficiency": None,
            "brand_savings_potential": None,
            "indulgence_tracker": None,
            "store_loyalty": None,
            "price_intelligence": None,
            "time_of_day_patterns": None,
            "payment_insights": None,
        }

    total_spend = sum(t.item_price for t in transactions if not t.is_discount and not t.is_deposit)
    weeks_in_period = max((date.today() - cutoff).days / 7, 1)

    # Store aggregation
    store_data: dict[str, dict] = defaultdict(lambda: {"spend": 0.0, "visits": set(), "items": 0})
    for t in transactions:
        if t.is_discount or t.is_deposit:
            continue
        store_data[t.store_name]["spend"] += t.item_price
        store_data[t.store_name]["visits"].add((t.receipt_id, t.date))
        store_data[t.store_name]["items"] += 1

    preferred_stores = sorted(
        [
            {
                "name": name,
                "spend": round(d["spend"], 2),
                "pct": round(d["spend"] / total_spend * 100, 1) if total_spend else 0,
                "visits": len(d["visits"]),
            }
            for name, d in store_data.items()
        ],
        key=lambda s: s["spend"],
        reverse=True,
    )

    # Category aggregation
    cat_data: dict[str, dict] = defaultdict(lambda: {"spend": 0.0, "count": 0})
    for t in transactions:
        if t.is_discount or t.is_deposit:
            continue
        cat_val = t.category if t.category else "Other"
        cat_data[cat_val]["spend"] += t.item_price
        cat_data[cat_val]["count"] += 1

    # Filter out "Other" category (contains discounts/deposits) and negative spend
    category_breakdown = sorted(
        [
            {
                "category": cat,
                "spend": round(d["spend"], 2),
                "pct": round(d["spend"] / total_spend * 100, 1) if total_spend else 0,
                "item_count": d["count"],
            }
            for cat, d in cat_data.items()
            if cat != "Other" and d["spend"] > 0
        ],
        key=lambda c: c["spend"],
        reverse=True,
    )

    # Premium ratio
    items_with_brand = [t for t in transactions if t.normalized_brand and not t.is_discount and not t.is_deposit]
    premium_count = sum(1 for t in items_with_brand if t.is_premium)
    premium_ratio = round(premium_count / len(items_with_brand), 2) if items_with_brand else 0

    # Granular categories (top 15, excluding "Discounts" and "Other" which are not product categories)
    gran_cat_counts: dict[str, int] = defaultdict(int)
    for t in transactions:
        if t.granular_category and t.granular_category not in ("Discounts", "Other"):
            gran_cat_counts[t.granular_category] += 1
    top_granular = [
        cat for cat, _ in sorted(gran_cat_counts.items(), key=lambda x: x[1], reverse=True)[:15]
    ]

    # Basket size
    receipt_item_counts: dict[str, int] = defaultdict(int)
    for t in transactions:
        if t.receipt_id and not t.is_discount and not t.is_deposit:
            receipt_item_counts[t.receipt_id] += 1
    typical_basket = (
        round(sum(receipt_item_counts.values()) / len(receipt_item_counts), 1)
        if receipt_item_counts
        else 0
    )

    # Preferred shopping days (day-of-week distribution, days above 10%)
    # Deduplicate to one entry per receipt/day to avoid weighting by basket size
    seen_receipt_days: set = set()
    for t in transactions:
        key = (t.receipt_id, t.date) if t.receipt_id else (None, t.date)
        seen_receipt_days.add(key)
    dow_counts = Counter(d.strftime("%A") for _, d in seen_receipt_days)
    total_dow = sum(dow_counts.values())
    preferred_shopping_days = sorted(
        [
            {"day": day, "pct": round(cnt / total_dow * 100, 1)}
            for day, cnt in dow_counts.items()
            if cnt / total_dow >= 0.10
        ],
        key=lambda d: d["pct"],
        reverse=True,
    )

    # Disposable bag spending — detect carrier bags so the LLM can suggest
    # bringing a reusable bag instead of searching for bag promotions.
    BAG_KEYWORDS = {"draagtas", "tas", "zak", "bag", "sachet", "carrier bag"}
    bag_txns = [
        t for t in transactions
        if t.normalized_name
        and any(kw in t.normalized_name.lower() for kw in BAG_KEYWORDS)
    ]
    bag_spending = None
    if bag_txns:
        bag_total = sum(t.item_price for t in bag_txns)
        bag_count = len(bag_txns)
        bag_spending = {
            "total_spent": round(bag_total, 2),
            "times_purchased": bag_count,
            "avg_price": round(bag_total / bag_count, 2),
            "estimated_yearly": round(bag_total / max(weeks_in_period, 1) * 52, 2),
        }

    # ── Aggregation 1: savings_summary ──
    discount_txns = [t for t in transactions if t.is_discount]
    savings_summary = None
    if discount_txns:
        total_saved = sum(t.item_price for t in discount_txns)
        total_spend_gross = total_spend + total_saved
        savings_rate_pct = round(total_saved / total_spend_gross * 100, 1) if total_spend_gross > 0 else 0

        # Per-store savings
        store_savings: dict[str, float] = defaultdict(float)
        store_net: dict[str, float] = defaultdict(float)
        for t in transactions:
            if t.is_discount:
                store_savings[t.store_name] += t.item_price
            elif not t.is_deposit:
                store_net[t.store_name] += t.item_price

        per_store_savings = []
        for s_name in store_savings:
            s_saved = store_savings[s_name]
            s_gross = store_net[s_name] + s_saved
            per_store_savings.append({
                "store": s_name,
                "saved": round(s_saved, 2),
                "rate_pct": round(s_saved / s_gross * 100, 1) if s_gross > 0 else 0,
            })
        per_store_savings.sort(key=lambda x: x["saved"], reverse=True)

        savings_summary = {
            "total_saved": round(total_saved, 2),
            "savings_rate_pct": savings_rate_pct,
            "monthly_savings_avg": round(total_saved / weeks_in_period * 4.33, 2),
            "per_store": per_store_savings[:10],
        }

    # ── Aggregation 2: shopping_efficiency ──
    receipt_groups: dict[str, list[Transaction]] = defaultdict(list)
    for t in transactions:
        if t.receipt_id:
            receipt_groups[t.receipt_id].append(t)

    shopping_efficiency = None
    if receipt_groups:
        small_trips = []
        weekday_totals = []
        weekend_totals = []
        for rid, r_txns in receipt_groups.items():
            non_discount_deposit_count = sum(1 for t in r_txns if not t.is_discount and not t.is_deposit)
            receipt_total = sum(t.item_price for t in r_txns if not t.is_discount and not t.is_deposit)
            receipt_date_val = r_txns[0].date

            if non_discount_deposit_count < 5:
                small_trips.append(receipt_total)

            if receipt_date_val.weekday() < 5:
                weekday_totals.append(receipt_total)
            else:
                weekend_totals.append(receipt_total)

        small_trips_count = len(small_trips)
        total_receipt_groups = len(receipt_groups)
        small_trips_pct = round(small_trips_count / total_receipt_groups * 100, 1) if total_receipt_groups > 0 else 0
        small_trips_avg_cost = round(sum(small_trips) / small_trips_count, 2) if small_trips_count > 0 else 0
        estimated_monthly = round(small_trips_avg_cost * (small_trips_count / weeks_in_period * 4.33), 2) if small_trips_count > 0 else 0

        weekday_avg = sum(weekday_totals) / len(weekday_totals) if weekday_totals else 0
        weekend_avg = sum(weekend_totals) / len(weekend_totals) if weekend_totals else 0
        weekend_premium_pct = round((weekend_avg - weekday_avg) / weekday_avg * 100, 1) if weekday_avg > 0 else 0

        shopping_efficiency = {
            "small_trips_count": small_trips_count,
            "small_trips_pct": small_trips_pct,
            "small_trips_avg_cost": small_trips_avg_cost,
            "small_trips_estimated_monthly": estimated_monthly,
            "weekday_avg_spend": round(weekday_avg, 2),
            "weekend_avg_spend": round(weekend_avg, 2),
            "weekend_premium_pct": weekend_premium_pct,
        }

    # ── Aggregation 4: brand_savings_potential ──
    real_txns = [t for t in transactions if not t.is_discount and not t.is_deposit]
    premium_spend = sum(t.item_price for t in real_txns if t.is_premium)
    house_brand_spend = sum(t.item_price for t in real_txns if not t.is_premium and t.normalized_brand)
    unbranded_spend = sum(t.item_price for t in real_txns if not t.normalized_brand)
    estimated_savings_full_switch = round(premium_spend * 0.25 / weeks_in_period * 4.33, 2) if premium_spend > 0 else 0

    brand_savings_potential = {
        "premium_spend": round(premium_spend, 2),
        "house_brand_spend": round(house_brand_spend, 2),
        "unbranded_spend": round(unbranded_spend, 2),
        "estimated_monthly_savings_if_switch": estimated_savings_full_switch,
    }

    # ── Aggregation 5: indulgence_tracker ──
    total_real_spend = sum(t.item_price for t in real_txns)
    alcohol_spend = sum(t.item_price for t in real_txns if t.category == "Alcohol")
    snacks_sweets_spend = sum(t.item_price for t in real_txns if t.category == "Snacks & Sweets")
    tobacco_spend = sum(t.item_price for t in real_txns if t.category == "Tobacco")
    total_indulgence = alcohol_spend + snacks_sweets_spend + tobacco_spend

    indulgence_tracker = {
        "alcohol_spend": round(alcohol_spend, 2),
        "snacks_sweets_spend": round(snacks_sweets_spend, 2),
        "tobacco_spend": round(tobacco_spend, 2),
        "total_indulgence": round(total_indulgence, 2),
        "indulgence_pct": round(total_indulgence / total_real_spend * 100, 1) if total_real_spend > 0 else 0,
        "estimated_yearly": round(total_indulgence / weeks_in_period * 52, 2),
    }

    # ── Aggregation 6: store_loyalty ──
    store_loyalty = None
    if store_data and total_spend != 0:
        total_store_spend = sum(d["spend"] for d in store_data.values())
        if total_store_spend > 0:
            shares = [d["spend"] / total_store_spend for d in store_data.values()]
            concentration_score = sum(s ** 2 for s in shares)
        else:
            concentration_score = 0

        # Category-store map (top 5 categories by spend)
        cat_store_spend: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        for t in transactions:
            if not t.is_discount and not t.is_deposit and t.category:
                cat_store_spend[t.category][t.store_name] += t.item_price
        cat_totals = {cat: sum(stores.values()) for cat, stores in cat_store_spend.items()}
        top_5_cats = sorted(cat_totals, key=cat_totals.get, reverse=True)[:5]  # type: ignore[arg-type]
        category_store_map = {}
        for cat in top_5_cats:
            stores_for_cat = cat_store_spend[cat]
            category_store_map[cat] = max(stores_for_cat, key=stores_for_cat.get)  # type: ignore[arg-type]

        store_loyalty = {
            "concentration_score": round(concentration_score, 3),
            "primary_store_pct": preferred_stores[0]["pct"] if preferred_stores else 0,
            "stores_visited_count": len(store_data),
            "category_store_map": category_store_map,
        }

    # ── Aggregation 7: time_of_day_patterns (uses new receipt_time field) ──
    time_of_day_patterns = None
    if receipts:
        timed_receipts = [r for r in receipts if r.receipt_time is not None]
        if len(timed_receipts) >= 3:
            morning = [r for r in timed_receipts if r.receipt_time.hour < 12]
            afternoon = [r for r in timed_receipts if 12 <= r.receipt_time.hour < 17]
            evening = [r for r in timed_receipts if r.receipt_time.hour >= 17]
            total_timed = len(timed_receipts)

            def _slot_stats(slot_receipts, label):
                if not slot_receipts:
                    return {"slot": label, "count": 0, "pct": 0, "avg_spend": 0}
                avg_spend = sum(r.total_amount or 0 for r in slot_receipts) / len(slot_receipts)
                return {
                    "slot": label,
                    "count": len(slot_receipts),
                    "pct": round(len(slot_receipts) / total_timed * 100, 1),
                    "avg_spend": round(avg_spend, 2),
                }

            time_of_day_patterns = {
                "morning": _slot_stats(morning, "morning"),
                "afternoon": _slot_stats(afternoon, "afternoon"),
                "evening": _slot_stats(evening, "evening"),
            }

    # ── Aggregation 9: payment_insights (uses new payment_method field) ──
    payment_insights = None
    if receipts:
        payment_receipts = [r for r in receipts if r.payment_method is not None]
        if len(payment_receipts) >= 3:
            method_data: dict[str, dict] = defaultdict(lambda: {"count": 0, "total": 0.0})
            for r in payment_receipts:
                method_data[r.payment_method]["count"] += 1
                method_data[r.payment_method]["total"] += r.total_amount or 0

            total_payment_count = len(payment_receipts)
            methods = []
            for method, d in method_data.items():
                methods.append({
                    "method": method,
                    "count": d["count"],
                    "pct": round(d["count"] / total_payment_count * 100, 1),
                    "total_spend": round(d["total"], 2),
                })
            methods.sort(key=lambda x: x["count"], reverse=True)

            mv_total = method_data.get("meal_vouchers", {}).get("total", 0)
            meal_voucher_monthly = round(mv_total / weeks_in_period * 4.33, 2) if mv_total else 0

            payment_insights = {
                "methods": methods,
                "meal_voucher_monthly": meal_voucher_monthly,
            }

    return {
        "total_spend": round(total_spend, 2),
        "receipt_count": receipt_count,
        "avg_receipt_total": round(total_spend / receipt_count, 2) if receipt_count else 0,
        "shopping_frequency_per_week": round(receipt_count / weeks_in_period, 1),
        "preferred_stores": preferred_stores[:10],
        "preferred_shopping_days": preferred_shopping_days,
        "category_breakdown": category_breakdown,
        "premium_brand_ratio": premium_ratio,
        "top_granular_categories": top_granular,
        "typical_basket_size": typical_basket,
        "disposable_bag_spending": bag_spending,
        "savings_summary": savings_summary,
        "shopping_efficiency": shopping_efficiency,
        "brand_savings_potential": brand_savings_potential,
        "indulgence_tracker": indulgence_tracker,
        "store_loyalty": store_loyalty,
        "time_of_day_patterns": time_of_day_patterns,
        "payment_insights": payment_insights,
    }


def _build_promo_interest_items(
    transactions: list[Transaction],
    cutoff: date,
) -> list[dict[str, Any]]:
    """Build a ranked list of up to 25 items most relevant for promotions."""
    if not transactions:
        return []

    weeks_in_period = max((date.today() - cutoff).days / 7, 1)

    # Aggregate per normalized_name
    item_data: dict[str, dict] = defaultdict(
        lambda: {
            "count": 0,
            "total_spend": 0.0,
            "total_quantity": 0,
            "receipt_ids": set(),
            "brands": set(),
            "store_names": Counter(),
            "is_premium_count": 0,
            "categories": set(),
            "granular_categories": set(),
            "dates": [],
            "product_names_no_brand": Counter(),
        }
    )

    for t in transactions:
        name = t.normalized_name or t.item_name
        if not name:
            continue
        name_lower = name.lower().strip()
        # Skip deposits and discounts (they don't represent actual products)
        if t.is_deposit or t.is_discount:
            continue
        # Skip items with "Other" granular_category — these are utility items
        # (carrier bags, etc.) that produce garbage promo search results
        if not t.granular_category or t.granular_category == "Other":
            continue

        item_data[name_lower]["count"] += 1
        item_data[name_lower]["total_spend"] += t.item_price
        item_data[name_lower]["total_quantity"] += t.quantity or 1
        if t.receipt_id:
            item_data[name_lower]["receipt_ids"].add(t.receipt_id)
        if t.normalized_brand:
            item_data[name_lower]["brands"].add(t.normalized_brand)
        if t.store_name:
            item_data[name_lower]["store_names"][t.store_name] += 1
        if t.is_premium:
            item_data[name_lower]["is_premium_count"] += 1
        if t.category:
            item_data[name_lower]["categories"].add(t.category)
        if t.granular_category:
            item_data[name_lower]["granular_categories"].add(t.granular_category)
        item_data[name_lower]["dates"].append(t.date)
        if t.dp_product_name_no_brand:
            item_data[name_lower]["product_names_no_brand"][t.dp_product_name_no_brand] += 1

    # Pre-compute category-level brand counts for loyalty classification
    # Exclude housebrand placeholders — they represent unbranded deli/bakery
    # items and would pollute brand analysis (no promo matches these).
    category_brand_counts: dict[str, Counter] = defaultdict(Counter)
    for t in transactions:
        if (t.granular_category
                and t.granular_category != "Other"
                and t.normalized_brand
                and t.normalized_brand != "in-house"
                and not t.normalized_brand.endswith("-housebrand")
                and not t.is_deposit
                and not t.is_discount):
            category_brand_counts[t.granular_category][t.normalized_brand] += 1

    # Precompute cross-item metrics for relative tags
    all_receipt_ids = {t.receipt_id for t in transactions if t.receipt_id}
    total_receipts_in_window = len(all_receipt_ids)
    item_prices = sorted(
        t.item_price for t in transactions
        if not t.is_deposit and not t.is_discount and t.item_price > 0
    )
    median_item_price = item_prices[len(item_prices) // 2] if item_prices else 0

    # Classify items into interest categories
    staples = []       # bought frequently (weekly+)
    high_spend = []    # top spend items
    brand_loyal = []   # consistently same premium brand
    bulk_buys = []     # items bought in bulk (multiple units per trip)
    price_switchers = []  # items bought across multiple brands — open to deals
    tried_recently = []   # items tried 1-2 times in last 30 days

    for name, data in item_data.items():
        trip_count = len(data["receipt_ids"]) or data["count"]
        freq_per_week = trip_count / weeks_in_period
        avg_price = data["total_spend"] / data["count"] if data["count"] else 0
        avg_units_per_trip = data["total_quantity"] / trip_count if trip_count else 0

        tags = []
        if freq_per_week >= 1:
            tags.append("weekly")
        elif freq_per_week >= 0.5:
            tags.append("biweekly")
        if data["is_premium_count"] > 0:
            tags.append("premium_brand")
        if avg_units_per_trip >= 2:
            tags.append("bulk")
        weekend_purchases = sum(1 for d in data["dates"] if d.weekday() >= 5)
        if data["dates"] and weekend_purchases / len(data["dates"]) >= 0.6:
            tags.append("weekend_buy")
        if total_receipts_in_window and trip_count / total_receipts_in_window >= 0.7:
            tags.append("basket_anchor")
        if median_item_price > 0 and avg_price >= median_item_price * 2:
            tags.append("splurge")

        # Temporal signals
        sorted_dates = sorted(set(data["dates"]))
        last_purchased = sorted_dates[-1]
        days_since = (date.today() - last_purchased).days

        avg_gap: float | None = None
        if len(sorted_dates) >= 2:
            gaps = [
                (sorted_dates[i + 1] - sorted_dates[i]).days
                for i in range(len(sorted_dates) - 1)
            ]
            avg_gap = round(sum(gaps) / len(gaps), 1)

        # Restock soon: approaching typical repurchase interval
        if avg_gap is not None and days_since >= avg_gap * 0.8:
            tags.append("restock_soon")

        # Trend detection: compare recent purchase gaps to overall
        if len(sorted_dates) >= 4 and avg_gap is not None and avg_gap > 0:
            recent_gaps = [
                (sorted_dates[i + 1] - sorted_dates[i]).days
                for i in range(len(sorted_dates) - 3, len(sorted_dates) - 1)
            ]
            avg_recent_gap = sum(recent_gaps) / len(recent_gaps)
            if avg_recent_gap > avg_gap * 1.5:
                tags.append("declining")
            elif avg_recent_gap < avg_gap * 0.6:
                tags.append("increasing")

        # Day-of-week distribution — pick top 1-2 days (>= 25% of trips)
        dow_counts = Counter(d.strftime("%A") for d in data["dates"])
        total_dow = sum(dow_counts.values())
        preferred_days = [
            day
            for day, cnt in dow_counts.most_common()
            if cnt / total_dow >= 0.25
        ][:2]

        # Determine primary store_name (most frequent)
        primary_store = data["store_names"].most_common(1)[0][0] if data["store_names"] else None

        # Build metrics dictionary with raw values (safe division)
        # Note for LLM: null values mean "insufficient data to calculate"
        total_spend = data["total_spend"]
        total_units = data["total_quantity"]
        restock_urgency = round(days_since / avg_gap, 2) if avg_gap and avg_gap > 0 else None
        metrics = {
            "total_spend": round(total_spend, 2),
            "trip_count": trip_count,
            "total_units": total_units,
            "avg_unit_price": round(total_spend / total_units, 2) if total_units > 0 else None,
            "avg_units_per_trip": round(total_units / trip_count, 2) if trip_count > 0 else None,
            "avg_spend_per_trip": round(total_spend / trip_count, 2) if trip_count > 0 else None,
            "purchase_frequency_days": avg_gap,  # avg days between purchases, null if < 2 purchases
            "days_since_last_purchase": days_since,
            "restock_urgency": restock_urgency,  # >1.0 = overdue, <1.0 = not yet due, null = insufficient data
        }

        entry = {
            "normalized_name": name,
            "product_name_no_brand": data["product_names_no_brand"].most_common(1)[0][0] if data["product_names_no_brand"] else None,
            "brands": sorted(data["brands"]) if data["brands"] else [],
            "store_name": primary_store,
            "granular_category": next(iter(data["granular_categories"]), None),
            "tags": tags,
            "metrics": metrics,
            "last_purchased": last_purchased.isoformat(),
            "preferred_days": preferred_days,
        }

        # Classify into interest buckets (copy entry so each bucket owns its dict)
        if freq_per_week >= 0.35 and trip_count >= 3:
            staples.append((trip_count, entry.copy()))

        if trip_count >= 2:
            high_spend.append((data["total_spend"], entry.copy()))

        # Brand analysis: use CATEGORY-level brand concentration
        # (not product-level, which is almost always single-brand)
        if data["brands"] and data["count"] >= 2 and trip_count >= 2:
            item_cat = next(iter(data["granular_categories"]), None)
            if item_cat:
                cat_brands = category_brand_counts.get(item_cat)
                if cat_brands and sum(cat_brands.values()) >= CATEGORY_BRAND_MIN_PURCHASES:
                    top_count = cat_brands.most_common(1)[0][1]
                    brand_share = top_count / sum(cat_brands.values())
                    if brand_share >= CATEGORY_BRAND_LOYAL_THRESHOLD:
                        brand_loyal.append((trip_count, entry.copy()))
                    elif len(cat_brands) >= 2:
                        e = entry.copy()
                        e["category_brands"] = sorted(cat_brands.keys())
                        price_switchers.append((trip_count, e))

        if avg_units_per_trip >= 2 and trip_count >= 2:
            bulk_buys.append((avg_units_per_trip, entry.copy()))

        # Tried recently: 1-2 purchases in the last 30 days, not frequent enough for staple
        recent_cutoff = date.today() - timedelta(days=30)
        recent_purchases = [d for d in sorted_dates if d >= recent_cutoff]
        if len(recent_purchases) in (1, 2) and freq_per_week < 0.5:
            tried_recently.append((-days_since, entry.copy()))

    # Sort each bucket and deduplicate across categories
    def _recency_key(x):
        """Primary metric first, then prefer more recently purchased items."""
        return (x[0], -x[1]["metrics"]["days_since_last_purchase"])

    staples.sort(key=_recency_key, reverse=True)
    high_spend.sort(key=_recency_key, reverse=True)
    brand_loyal.sort(key=_recency_key, reverse=True)
    bulk_buys.sort(key=_recency_key, reverse=True)
    price_switchers.sort(key=_recency_key, reverse=True)
    tried_recently.sort(key=lambda x: x[0], reverse=True)  # most recent first

    # Allocate slots with guaranteed minimum of 1 per non-empty bucket
    result = []
    seen_names: set[str] = set()
    category_counts: dict[str, int] = defaultdict(int)  # track per-category totals across passes

    def _add_items(bucket: list, category: str, max_count: int) -> int:
        added = 0
        for _, entry in bucket:
            if len(result) >= MAX_INTEREST_ITEMS:
                break
            if category_counts[category] >= max_count:
                break
            if entry["normalized_name"] in seen_names:
                continue
            seen_names.add(entry["normalized_name"])
            entry["interest_category"] = category
            result.append(entry)
            added += 1
            category_counts[category] += 1
        return added

    # Bucket definitions: (list, category_name, max_slots)
    buckets = [
        (staples, "staple", 8),
        (high_spend, "top_purchase", 6),
        (brand_loyal, "brand_loyal", 4),
        (price_switchers, "price_switcher", 4),
        (bulk_buys, "bulk_buy", 3),
        (tried_recently, "tried_recently", 2),
    ]

    # Pass 1: guarantee at least 1 item per non-empty bucket
    for bucket, category, _ in buckets:
        _add_items(bucket, category, 1)

    # Pass 2: fill remaining slots up to each bucket's max
    for bucket, category, max_count in buckets:
        _add_items(bucket, category, max_count)

    # Pass 3: Add category-level interests if we have sparse item-level data
    # This helps users with few receipts still get relevant promo recommendations
    MIN_ITEMS_BEFORE_CATEGORY_FALLBACK = 5
    MAX_CATEGORY_ITEMS = 3

    if len(result) < MIN_ITEMS_BEFORE_CATEGORY_FALLBACK:
        # Aggregate category-level data (excluding Discounts and Other)
        category_data: dict[str, dict] = defaultdict(
            lambda: {
                "total_spend": 0.0,
                "total_units": 0,
                "receipt_ids": set(),
                "dates": [],
            }
        )
        for t in transactions:
            if t.granular_category and t.granular_category not in ("Discounts", "Other"):
                if not t.is_deposit and not t.is_discount:
                    category_data[t.granular_category]["total_spend"] += t.item_price
                    category_data[t.granular_category]["total_units"] += t.quantity or 1
                    if t.receipt_id:
                        category_data[t.granular_category]["receipt_ids"].add(t.receipt_id)
                    category_data[t.granular_category]["dates"].append(t.date)

        # Get categories already represented in results
        represented_categories = {item.get("granular_category") for item in result}

        # Sort by spend and add category-level items
        sorted_categories = sorted(
            category_data.items(), key=lambda x: x[1]["total_spend"], reverse=True
        )
        category_items_added = 0

        for cat, data in sorted_categories:
            if len(result) >= MAX_INTEREST_ITEMS:
                break
            if category_items_added >= MAX_CATEGORY_ITEMS:
                break
            if cat in represented_categories:
                continue

            # Compute category-level metrics
            cat_spend = data["total_spend"]
            cat_units = data["total_units"]
            cat_trip_count = len(data["receipt_ids"]) or len(data["dates"])
            cat_dates = sorted(set(data["dates"])) if data["dates"] else []
            cat_last_purchased = cat_dates[-1] if cat_dates else None
            cat_days_since = (date.today() - cat_last_purchased).days if cat_last_purchased else None

            # Compute avg days between purchases for category
            cat_avg_gap: float | None = None
            if len(cat_dates) >= 2:
                gaps = [(cat_dates[i + 1] - cat_dates[i]).days for i in range(len(cat_dates) - 1)]
                cat_avg_gap = round(sum(gaps) / len(gaps), 1)

            # Compute restock urgency
            cat_restock_urgency = round(cat_days_since / cat_avg_gap, 2) if cat_avg_gap and cat_avg_gap > 0 and cat_days_since else None

            # Add a category-level interest item (no specific product)
            result.append({
                "normalized_name": cat.lower(),  # Use category name as search term
                "brands": [],
                "store_name": None,
                "granular_category": cat,
                "tags": ["category_level"],
                "is_category_fallback": True,  # Explicit flag for LLM
                "metrics": {
                    "total_spend": round(cat_spend, 2),
                    "trip_count": cat_trip_count,
                    "total_units": cat_units,
                    "avg_unit_price": round(cat_spend / cat_units, 2) if cat_units > 0 else None,
                    "avg_units_per_trip": round(cat_units / cat_trip_count, 2) if cat_trip_count > 0 else None,
                    "avg_spend_per_trip": round(cat_spend / cat_trip_count, 2) if cat_trip_count > 0 else None,
                    "purchase_frequency_days": cat_avg_gap,  # null if < 2 purchases
                    "days_since_last_purchase": cat_days_since,
                    "restock_urgency": cat_restock_urgency,  # >1.0 = overdue, null = insufficient data
                },
                "last_purchased": cat_last_purchased.isoformat() if cat_last_purchased else None,
                "preferred_days": [],
                "interest_category": "category_fallback",
            })
            represented_categories.add(cat)
            category_items_added += 1

    return result
