import logging
from collections import Counter, defaultdict
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import invalidate_user
from app.models.transaction import Transaction
from app.models.receipt import Receipt
from app.models.enums import LoyaltyStatus, ReceiptStatus
from app.db.repositories.enriched_profile_repo import EnrichedProfileRepository

logger = logging.getLogger(__name__)

# How many days of history to aggregate
LOOKBACK_DAYS = 180


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
            category_profiles = _build_category_profiles(transactions, cutoff)

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
                category_profiles=category_profiles,
                data_period_start=period_start,
                data_period_end=period_end,
                receipts_analyzed=receipt_count,
            )

            # Invalidate analytics/budget cache since transaction data has changed
            invalidate_user(user_id)

            logger.info(
                f"Enriched profile rebuilt for user {user_id}: "
                f"{receipt_count} receipts, {len(transactions)} transactions, "
                f"{len(category_profiles)} category profiles"
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

    total_spend = sum((-t.item_price if t.is_discount else t.item_price) for t in transactions if not t.is_deposit)
    weeks_in_period = max((date.today() - cutoff).days / 7, 1)

    # Store aggregation
    store_data: dict[str, dict] = defaultdict(lambda: {"spend": 0.0, "visits": set(), "items": 0})
    for t in transactions:
        if t.is_deposit:
            continue
        amount = -t.item_price if t.is_discount else t.item_price
        store_data[t.store_name]["spend"] += amount
        store_data[t.store_name]["visits"].add((t.receipt_id, t.date))
        if not t.is_discount:
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
        if t.is_deposit:
            continue
        cat_val = t.category if t.category else "Other"
        amount = -t.item_price if t.is_discount else t.item_price
        cat_data[cat_val]["spend"] += amount
        if not t.is_discount:
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
            receipt_total = sum((-t.item_price if t.is_discount else t.item_price) for t in r_txns if not t.is_deposit)
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



# ---------------------------------------------------------------------------
# Category profiles for promo-first matching
# ---------------------------------------------------------------------------
# Loyalty thresholds
_STRICTLY_LOYAL_THRESHOLD = 0.80
_SOFT_LOYAL_THRESHOLD = 0.60
_MIN_EVENTS_FOR_LOYALTY = 3


def _build_category_profiles(
    transactions: list[Transaction],
    cutoff: date,
) -> dict[str, dict[str, Any]]:
    """Build per-granular-category purchase profiles for promo recommendation.

    Returns a dict keyed by granular_category with purchase frequency,
    brand loyalty, and restock urgency signals.
    """
    if not transactions:
        return {}

    # Aggregate per granular_category
    cat_data: dict[str, dict] = defaultdict(
        lambda: {
            "total_spend": 0.0,
            "total_items": 0,
            "receipt_ids": set(),
            "brand_counts": Counter(),
            "premium_count": 0,
            "dates": [],
        }
    )

    for t in transactions:
        if not t.granular_category or t.granular_category in ("Other", "Discount"):
            continue
        if t.is_deposit or t.is_discount:
            continue

        cat = t.granular_category
        cat_data[cat]["total_spend"] += t.item_price
        cat_data[cat]["total_items"] += t.quantity or 1
        if t.receipt_id:
            cat_data[cat]["receipt_ids"].add(t.receipt_id)
        if t.normalized_brand and not t.normalized_brand.endswith("-housebrand"):
            cat_data[cat]["brand_counts"][t.normalized_brand] += 1
        if t.is_premium:
            cat_data[cat]["premium_count"] += 1
        cat_data[cat]["dates"].append(t.date)

    profiles: dict[str, dict[str, Any]] = {}

    for cat, data in cat_data.items():
        total_purchase_events = len(data["receipt_ids"]) or len(data["dates"])
        if total_purchase_events == 0:
            continue

        sorted_dates = sorted(set(data["dates"]))
        last_purchase = sorted_dates[-1]
        days_since = (date.today() - last_purchase).days

        # Average days between purchases (true historical average, O(1))
        avg_days_between: float | None = None
        restock_urgency: float | None = None
        if len(sorted_dates) >= 2:
            span = (sorted_dates[-1] - sorted_dates[0]).days
            avg_days_between = round(span / (len(sorted_dates) - 1), 1)

            if avg_days_between > 0:
                raw_urgency = days_since / avg_days_between
                # Churn cutoff: if they missed 3+ expected cycles, they abandoned it
                restock_urgency = round(raw_urgency, 2) if raw_urgency <= 3.0 else 0.0

        # Brand loyalty classification
        brand_counts = data["brand_counts"]
        total_branded = sum(brand_counts.values())
        preferred_brand: str | None = None

        if total_purchase_events < _MIN_EVENTS_FOR_LOYALTY:
            loyalty_status = LoyaltyStatus.NEW.value
        elif total_branded == 0:
            # All purchases are housebrands or unbranded
            loyalty_status = LoyaltyStatus.BRAND_AGNOSTIC.value
        else:
            top_brand, top_count = brand_counts.most_common(1)[0]
            brand_share = top_count / total_branded
            if brand_share >= _STRICTLY_LOYAL_THRESHOLD:
                loyalty_status = LoyaltyStatus.STRICTLY_LOYAL.value
                preferred_brand = top_brand
            elif brand_share >= _SOFT_LOYAL_THRESHOLD:
                loyalty_status = LoyaltyStatus.SOFT_LOYAL.value
                preferred_brand = top_brand
            else:
                loyalty_status = LoyaltyStatus.BRAND_AGNOSTIC.value

        profiles[cat] = {
            "total_purchase_events": total_purchase_events,
            "average_days_between": avg_days_between,
            "avg_price_paid": round(data["total_spend"] / data["total_items"], 2) if data["total_items"] > 0 else None,
            "total_spend": round(data["total_spend"], 2),
            "brand_tally": dict(brand_counts),
            "loyalty_status": loyalty_status,
            "preferred_brand": preferred_brand,
            "is_premium_buyer": data["premium_count"] / data["total_items"] > 0.5 if data["total_items"] > 0 else False,
            "last_purchase_date": last_purchase.isoformat(),
            "restock_urgency": restock_urgency,
        }

    return profiles
