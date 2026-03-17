"""Promo report service: deterministic assembly from pre-computed candidates.

At serve time, fetches the weekly candidate pool, filters by the user's
current preferred_stores, and assembles the response deterministically.
No Pinecone search or Gemini calls happen at request time.
"""

from datetime import date
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.promo_reports import (
    build_empty_promo_response,
    compute_promo_week,
    current_brussels_date,
)
from app.db.repositories.enriched_profile_repo import EnrichedProfileRepository
from app.db.repositories.promo_report_event_repo import PromoReportEventRepository
from app.db.repositories.promo_weekly_candidates_repo import PromoWeeklyCandidatesRepository
from app.models.enums import PromoReportEventType, PromoReportStatus
from app.models.user import User
from app.models.user_profile import UserProfile


class PromoReportNotFoundError(Exception):
    def __init__(self, report_id: str):
        self.report_id = report_id
        super().__init__(f"Promo weekly candidates not found: {report_id}")


class PromoReportService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.enriched_repo = EnrichedProfileRepository(db)
        self.candidates_repo = PromoWeeklyCandidatesRepository(db)
        self.event_repo = PromoReportEventRepository(db)

    async def get_current_report_response(
        self,
        user_id: str,
        report_date: Optional[date] = None,
    ) -> dict:
        """Assemble a promo report from pre-computed candidates, filtered by preferred_stores."""
        report_date = report_date or current_brussels_date()
        promo_week = compute_promo_week(report_date)

        # Check enriched profile exists
        enriched_profile = await self.enriched_repo.get_by_user_id(user_id)
        if enriched_profile is None:
            return build_empty_promo_response(
                report_status=PromoReportStatus.NO_ENRICHED_PROFILE,
                message="Keep scanning receipts to unlock your weekly deals.",
                report_date=report_date,
            )

        # Fetch candidates for current week
        candidates_row = await self.candidates_repo.get_by_user_and_week(
            user_id,
            promo_week["iso_year"],
            promo_week["iso_week"],
        )
        if candidates_row is None:
            return build_empty_promo_response(
                report_status=PromoReportStatus.NO_REPORT_AVAILABLE,
                message="This week's deals are not ready yet.",
                report_date=report_date,
            )

        # Fetch user's current preferred_stores
        preferred_stores = await self._fetch_preferred_stores(user_id)

        # Assemble deterministically
        return self._assemble_report(
            candidates_row=candidates_row,
            preferred_stores=preferred_stores,
            promo_week=promo_week,
        )

    async def log_event(
        self,
        *,
        user_id: str,
        report_id: str,
        event_type: PromoReportEventType,
        item_key: Optional[str] = None,
        store_name: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> None:
        candidates = await self.candidates_repo.get_by_id_for_user(report_id, user_id)
        if candidates is None:
            raise PromoReportNotFoundError(report_id)

        await self.event_repo.create(
            report_id=candidates.id,
            user_id=user_id,
            iso_year=candidates.iso_year,
            iso_week=candidates.iso_week,
            event_type=event_type,
            item_key=item_key,
            store_name=store_name,
            metadata_json=metadata,
        )

    async def _fetch_preferred_stores(self, user_id: str) -> list[str]:
        """Fetch preferred_stores from UserProfile (joined via firebase_uid)."""
        result = await self.db.execute(
            select(UserProfile.preferred_stores)
            .join(User, User.firebase_uid == UserProfile.user_id)
            .where(User.id == user_id)
        )
        row = result.one_or_none()
        if row and row[0]:
            return row[0]
        return []

    def _assemble_report(
        self,
        candidates_row,
        preferred_stores: list[str],
        promo_week: dict,
    ) -> dict:
        """Deterministic assembly: filter, rank, group, compute totals."""
        items = list(candidates_row.candidates_json or [])

        # 1. Filter by preferred_stores ([] = all stores)
        if preferred_stores:
            store_set = {s.lower() for s in preferred_stores}
            items = [i for i in items if i.get("store_name", "").lower() in store_set]

        if not items:
            return build_empty_promo_response(
                report_status=PromoReportStatus.READY,
                message="No active deals matched your habits this week.",
                report_date=candidates_row.report_date,
            )

        # 2. Score and rank
        for item in items:
            urgency = item.get("restock_urgency") or 0.5
            freq_days = item.get("purchase_frequency_days") or 30
            savings = item.get("savings", 0)
            item["_score"] = savings * min(urgency, 3.0) * (30 / max(freq_days, 1))

        items.sort(key=lambda x: x.get("_score", 0), reverse=True)

        # 3. Top 3 = top_picks, rest = store items
        top_pick_items = items[:3]
        remaining_items = items[3:]

        # 4. Build top_picks
        top_picks = []
        for item in top_pick_items:
            top_picks.append({
                "item_key": item.get("item_key"),
                "brand": item.get("brand", ""),
                "product_name": item.get("product_name", ""),
                "emoji": item.get("emoji", "🛒"),
                "store": item.get("store_name", ""),
                "original_price": item.get("original_price", 0),
                "promo_price": item.get("promo_price", 0),
                "savings": item.get("savings", 0),
                "discount_percentage": item.get("discount_percentage", 0),
                "mechanism": item.get("mechanism", ""),
                "validity_start": item.get("validity_start", ""),
                "validity_end": item.get("validity_end", ""),
                "reason": item.get("reason", ""),
                "page_number": item.get("page_number"),
                "promo_folder_url": item.get("promo_folder_url"),
            })

        # 5. Group remaining by store
        store_tips = candidates_row.store_tips_json or {}
        stores_dict: dict[str, list[dict]] = {}
        for item in remaining_items:
            store_name = item.get("store_name", "Unknown")
            if store_name not in stores_dict:
                stores_dict[store_name] = []
            stores_dict[store_name].append({
                "item_key": item.get("item_key"),
                "brand": item.get("brand", ""),
                "product_name": item.get("product_name", ""),
                "emoji": item.get("emoji", "🛒"),
                "original_price": item.get("original_price", 0),
                "promo_price": item.get("promo_price", 0),
                "savings": item.get("savings", 0),
                "discount_percentage": item.get("discount_percentage", 0),
                "mechanism": item.get("mechanism", ""),
                "validity_start": item.get("validity_start", ""),
                "validity_end": item.get("validity_end", ""),
                "page_number": item.get("page_number"),
                "promo_folder_url": item.get("promo_folder_url"),
            })

        stores = []
        for store_name, store_items in stores_dict.items():
            total_savings = round(sum(i.get("savings", 0) for i in store_items), 2)
            validity_end = max(
                (i.get("validity_end", "") for i in store_items),
                default="",
            )
            store_color = store_items[0].get("store_color", "⬜") if store_items else "⬜"
            # Get store_color from the first candidate that has this store
            for item in items:
                if item.get("store_name") == store_name:
                    store_color = item.get("store_color", "⬜")
                    break
            stores.append({
                "store_name": store_name,
                "store_color": store_color,
                "total_savings": total_savings,
                "validity_end": validity_end,
                "items": store_items,
                "tip": store_tips.get(store_name, ""),
            })

        # Sort stores by total_savings descending
        stores.sort(key=lambda s: s["total_savings"], reverse=True)

        # 6. Select smart_switch from pre-computed candidates
        smart_switch = self._select_smart_switch(
            candidates_row.smart_switch_json,
            preferred_stores,
        )

        # 7. Compute summary
        all_savings = [i.get("savings", 0) for i in items]
        total_savings = round(sum(all_savings), 2)
        deal_count = len(items)

        stores_breakdown = []
        # Include top_picks in store breakdown
        store_items_count: dict[str, dict] = {}
        for item in items:
            sn = item.get("store_name", "Unknown")
            if sn not in store_items_count:
                store_items_count[sn] = {"items": 0, "savings": 0.0}
            store_items_count[sn]["items"] += 1
            store_items_count[sn]["savings"] += item.get("savings", 0)

        for sn, data in store_items_count.items():
            stores_breakdown.append({
                "store": sn,
                "items": data["items"],
                "savings": round(data["savings"], 2),
            })
        stores_breakdown.sort(key=lambda x: x["savings"], reverse=True)

        best_value = stores_breakdown[0] if stores_breakdown else None

        summary = {
            "total_items": deal_count,
            "total_savings": total_savings,
            "stores_breakdown": stores_breakdown,
            "best_value_store": best_value["store"] if best_value else None,
            "best_value_savings": best_value["savings"] if best_value else 0,
            "best_value_items": best_value["items"] if best_value else 0,
            "closing_nudge": candidates_row.closing_nudge or "",
        }

        return {
            "report_id": candidates_row.id,
            "report_status": PromoReportStatus.READY.value,
            "message": "Your weekly deals are ready." if deal_count > 0 else "No active deals matched your habits this week.",
            "generated_at": candidates_row.generated_at.isoformat() if candidates_row.generated_at else None,
            "weekly_savings": total_savings,
            "deal_count": deal_count,
            "promo_week": promo_week,
            "top_picks": top_picks,
            "stores": stores,
            "smart_switch": smart_switch,
            "summary": summary,
        }

    @staticmethod
    def _select_smart_switch(
        smart_switch_json: Optional[list],
        preferred_stores: list[str],
    ) -> Optional[dict]:
        """Select the best smart_switch from pre-computed candidates, filtered by visible stores."""
        if not smart_switch_json:
            return None

        store_set = {s.lower() for s in preferred_stores} if preferred_stores else set()

        for ss in smart_switch_json:
            ss_store = (ss.get("store_name") or "").lower()
            if store_set and ss_store not in store_set:
                continue
            return {
                "from_brand": ss.get("from_brand", ""),
                "to_brand": ss.get("to_brand", ""),
                "emoji": ss.get("emoji", "🛒"),
                "product_type": ss.get("product_type", ""),
                "savings": ss.get("savings", 0),
                "mechanism": ss.get("mechanism", ""),
                "reason": ss.get("reason", ""),
            }

        return None
