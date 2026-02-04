import logging
from collections import Counter, defaultdict
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.transaction import Transaction
from app.models.receipt import Receipt
from app.models.enums import ReceiptStatus
from app.db.repositories.enriched_profile_repo import EnrichedProfileRepository

logger = logging.getLogger(__name__)

# How many days of history to aggregate
LOOKBACK_DAYS = 90
# Max promo interest items
MAX_INTEREST_ITEMS = 25


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

            # Build aggregated data
            shopping_habits = _build_shopping_habits(transactions, receipt_count, cutoff)
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
            "avg_health_score": None,
            "premium_brand_ratio": 0,
            "top_granular_categories": [],
            "typical_basket_size": 0,
        }

    total_spend = sum(t.item_price for t in transactions)
    weeks_in_period = max((date.today() - cutoff).days / 7, 1)

    # Store aggregation
    store_data: dict[str, dict] = defaultdict(lambda: {"spend": 0.0, "visits": set(), "items": 0})
    for t in transactions:
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
    cat_data: dict[str, dict] = defaultdict(lambda: {"spend": 0.0, "health_scores": [], "count": 0})
    for t in transactions:
        cat_val = t.category.value if t.category else "Other"
        cat_data[cat_val]["spend"] += t.item_price
        cat_data[cat_val]["count"] += 1
        if t.health_score is not None:
            cat_data[cat_val]["health_scores"].append(t.health_score)

    category_breakdown = sorted(
        [
            {
                "category": cat,
                "spend": round(d["spend"], 2),
                "pct": round(d["spend"] / total_spend * 100, 1) if total_spend else 0,
                "item_count": d["count"],
                "avg_health": round(sum(d["health_scores"]) / len(d["health_scores"]), 1)
                if d["health_scores"]
                else None,
            }
            for cat, d in cat_data.items()
        ],
        key=lambda c: c["spend"],
        reverse=True,
    )

    # Health score
    health_scores = [t.health_score for t in transactions if t.health_score is not None]
    avg_health = round(sum(health_scores) / len(health_scores), 1) if health_scores else None

    # Premium ratio
    items_with_brand = [t for t in transactions if t.normalized_brand]
    premium_count = sum(1 for t in items_with_brand if t.is_premium)
    premium_ratio = round(premium_count / len(items_with_brand), 2) if items_with_brand else 0

    # Granular categories (top 15)
    gran_cat_counts: dict[str, int] = defaultdict(int)
    for t in transactions:
        if t.granular_category:
            gran_cat_counts[t.granular_category] += 1
    top_granular = [
        cat for cat, _ in sorted(gran_cat_counts.items(), key=lambda x: x[1], reverse=True)[:15]
    ]

    # Basket size
    receipt_item_counts: dict[str, int] = defaultdict(int)
    for t in transactions:
        if t.receipt_id:
            receipt_item_counts[t.receipt_id] += 1
    typical_basket = (
        round(sum(receipt_item_counts.values()) / len(receipt_item_counts), 1)
        if receipt_item_counts
        else 0
    )

    # Preferred shopping days (day-of-week distribution, days above 10%)
    dow_counts = Counter(t.date.strftime("%A") for t in transactions)
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

    return {
        "total_spend": round(total_spend, 2),
        "receipt_count": receipt_count,
        "avg_receipt_total": round(total_spend / receipt_count, 2) if receipt_count else 0,
        "shopping_frequency_per_week": round(receipt_count / weeks_in_period, 1),
        "preferred_stores": preferred_stores[:10],
        "preferred_shopping_days": preferred_shopping_days,
        "category_breakdown": category_breakdown,
        "avg_health_score": avg_health,
        "premium_brand_ratio": premium_ratio,
        "top_granular_categories": top_granular,
        "typical_basket_size": typical_basket,
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
            "is_premium_count": 0,
            "health_scores": [],
            "categories": set(),
            "granular_categories": set(),
            "dates": [],
        }
    )

    for t in transactions:
        name = t.normalized_name or t.item_name
        if not name:
            continue
        name_lower = name.lower().strip()
        # Skip deposits
        if t.is_deposit:
            continue

        item_data[name_lower]["count"] += 1
        item_data[name_lower]["total_spend"] += t.item_price
        item_data[name_lower]["total_quantity"] += t.quantity or 1
        if t.receipt_id:
            item_data[name_lower]["receipt_ids"].add(t.receipt_id)
        if t.normalized_brand:
            item_data[name_lower]["brands"].add(t.normalized_brand)
        if t.is_premium:
            item_data[name_lower]["is_premium_count"] += 1
        if t.health_score is not None:
            item_data[name_lower]["health_scores"].append(t.health_score)
        if t.category:
            item_data[name_lower]["categories"].add(t.category.value)
        if t.granular_category:
            item_data[name_lower]["granular_categories"].add(t.granular_category)
        item_data[name_lower]["dates"].append(t.date)

    # Classify items into interest categories
    staples = []       # bought frequently (weekly+)
    high_spend = []    # top spend items
    brand_loyal = []   # consistently same premium brand
    health_picks = []  # healthy items bought regularly
    treats = []        # indulgence items bought periodically
    bulk_buys = []     # items bought in bulk (multiple units per trip)

    for name, data in item_data.items():
        trip_count = len(data["receipt_ids"]) or data["count"]
        freq_per_week = trip_count / weeks_in_period
        avg_price = data["total_spend"] / data["count"] if data["count"] else 0
        avg_units_per_trip = data["total_quantity"] / trip_count if trip_count else 0
        avg_health = (
            sum(data["health_scores"]) / len(data["health_scores"])
            if data["health_scores"]
            else None
        )

        tags = []
        if freq_per_week >= 1:
            tags.append("weekly")
        elif freq_per_week >= 0.5:
            tags.append("biweekly")
        if data["is_premium_count"] > 0:
            tags.append("premium_brand")
        if avg_health is not None and avg_health >= 4:
            tags.append("healthy")
        if avg_health is not None and avg_health <= 2:
            tags.append("indulgence")
        if avg_units_per_trip >= 2:
            tags.append("bulk")

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

        # Day-of-week distribution — pick top 1-2 days (>= 25% of trips)
        dow_counts = Counter(d.strftime("%A") for d in data["dates"])
        total_dow = sum(dow_counts.values())
        preferred_days = [
            day
            for day, cnt in dow_counts.most_common()
            if cnt / total_dow >= 0.25
        ][:2]

        # Build context string with temporal info
        context_parts = [
            f"Bought on {trip_count} trips in 3mo "
            f"({freq_per_week:.1f}/week), "
            f"avg {chr(0x20AC)}{avg_price:.2f}, "
            f"avg {avg_units_per_trip:.1f} units/trip",
        ]
        context_parts.append(f"Last bought {days_since} days ago")
        if avg_gap is not None:
            context_parts.append(f"typically every {avg_gap} days")
        if preferred_days:
            context_parts.append(f"mostly on {', '.join(d[:3] for d in preferred_days)}")

        entry = {
            "normalized_name": name,
            "brands": sorted(data["brands"]) if data["brands"] else [],
            "granular_category": next(iter(data["granular_categories"]), None),
            "tags": tags,
            "last_purchased": last_purchased.isoformat(),
            "days_since_last_purchase": days_since,
            "avg_days_between_purchases": avg_gap,
            "preferred_days": preferred_days,
            "context": ". ".join(context_parts),
        }

        # Classify
        if freq_per_week >= 0.5 and trip_count >= 3:
            staples.append((trip_count, entry))

        if trip_count >= 2:
            high_spend.append((data["total_spend"], entry))

        # Brand loyal: dominant brand accounts for >= 80% of purchases
        if data["brands"] and data["count"] >= 2 and trip_count >= 2:
            brand_counts: dict[str, int] = defaultdict(int)
            for bt in transactions:
                bt_name = bt.normalized_name or bt.item_name
                if bt_name and bt_name.lower().strip() == name and bt.normalized_brand:
                    brand_counts[bt.normalized_brand] += 1
            if brand_counts:
                top_brand_count = max(brand_counts.values())
                brand_ratio = top_brand_count / data["count"]
                if brand_ratio >= 0.8:
                    brand_loyal.append((trip_count, entry))

        if avg_health is not None and avg_health >= 4 and trip_count >= 3:
            health_picks.append((avg_health, entry))

        if avg_health is not None and avg_health <= 2 and trip_count >= 2:
            treats.append((trip_count, entry))

        if avg_units_per_trip >= 2 and trip_count >= 2:
            bulk_buys.append((avg_units_per_trip, entry))

    # Sort each bucket and deduplicate across categories
    staples.sort(key=lambda x: x[0], reverse=True)
    high_spend.sort(key=lambda x: x[0], reverse=True)
    brand_loyal.sort(key=lambda x: x[0], reverse=True)
    health_picks.sort(key=lambda x: x[0], reverse=True)
    treats.sort(key=lambda x: x[0], reverse=True)
    bulk_buys.sort(key=lambda x: x[0], reverse=True)

    # Allocate slots with guaranteed minimum of 1 per non-empty bucket
    result = []
    seen_names: set[str] = set()

    def _add_items(bucket: list, category: str, max_count: int) -> int:
        added = 0
        for _, entry in bucket:
            if len(result) >= MAX_INTEREST_ITEMS:
                break
            if added >= max_count:
                break
            if entry["normalized_name"] in seen_names:
                continue
            seen_names.add(entry["normalized_name"])
            entry["interest_category"] = category
            result.append(entry)
            added += 1
        return added

    buckets = [
        (staples, "staple", 8),
        (high_spend, "high_spend", 6),
        (brand_loyal, "brand_loyal", 4),
        (health_picks, "health_pick", 4),
        (treats, "occasional_treat", 3),
        (bulk_buys, "bulk_buy", 3),
    ]

    # Pass 1: guarantee at least 1 item per non-empty bucket
    for bucket, category, _ in buckets:
        _add_items(bucket, category, 1)

    # Pass 2: fill remaining slots up to each bucket's max
    for bucket, category, max_count in buckets:
        _add_items(bucket, category, max_count)

    return result
