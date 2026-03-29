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
from app.core.stores import resolve_store_name
from app.db.repositories.enriched_profile_repo import EnrichedProfileRepository
from app.db.repositories.promo_report_event_repo import PromoReportEventRepository
from app.db.repositories.promo_candidates_repo import PromoCandidatesRepository
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
        self.candidates_repo = PromoCandidatesRepository(db)
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

        # Fetch candidates for user
        candidates_row = await self.candidates_repo.get_by_user(user_id)
        if candidates_row is None:
            return build_empty_promo_response(
                report_status=PromoReportStatus.NO_REPORT_AVAILABLE,
                message="This week's deals are not ready yet.",
                report_date=report_date,
            )

        # Fetch user's current preferred_stores
        preferred_stores = await self._fetch_preferred_stores(user_id)

        # No stores selected → tell the user to pick stores
        if preferred_stores is not None and len(preferred_stores) == 0:
            resp = build_empty_promo_response(
                report_status=PromoReportStatus.READY,
                message="Select at least one store in the Deals tab to see personalised deals.",
                report_date=report_date,
            )
            resp["preferred_stores"] = []
            return resp

        # Assemble deterministically
        return self._assemble_report(
            candidates_row=candidates_row,
            preferred_stores=preferred_stores or [],
            promo_week=promo_week,
            report_date=report_date,
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
            event_type=event_type,
            item_key=item_key,
            store_name=store_name,
            metadata_json=metadata,
        )

    async def _fetch_preferred_stores(self, user_id: str) -> list[str] | None:
        """Fetch preferred_stores from UserProfile (joined via firebase_uid).

        Returns the list (possibly empty) or None if no profile exists.
        """
        result = await self.db.execute(
            select(UserProfile.preferred_stores)
            .join(User, User.firebase_uid == UserProfile.user_id)
            .where(User.id == user_id)
        )
        row = result.one_or_none()
        if row is None:
            return None
        return row[0] if row[0] is not None else []

    def _assemble_report(
        self,
        candidates_row,
        preferred_stores: list[str],
        promo_week: dict,
        report_date: Optional[date] = None,
    ) -> dict:
        """Deterministic assembly: filter, rank, group, compute totals."""
        items = list(candidates_row.candidates_json or [])
        today_str = report_date.isoformat() if report_date else current_brussels_date().isoformat()

        # 0. Filter out expired promos (validity_end < today)
        items = [i for i in items if (i.get("validity_end") or "") >= today_str]

        # 1. Filter by preferred_stores (empty list is handled before this method)
        #    Resolve display names → canonical names defensively (handles both old and new format)
        canonical_preferred = [resolve_store_name(s) or s.lower() for s in preferred_stores] if preferred_stores else []
        if canonical_preferred:
            store_set = set(canonical_preferred)
            items = [i for i in items if i.get("store_name", "").lower() in store_set]

        if not items:
            resp = build_empty_promo_response(
                report_status=PromoReportStatus.READY,
                message="No deals matched your shopping habits this week. Upload more receipts so we can find better deals for you!",
                report_date=candidates_row.report_date,
            )
            resp["preferred_stores"] = canonical_preferred
            return resp

        # 2. Sort by pre-computed score (from candidate generation)
        items.sort(key=lambda x: x.get("score", 0), reverse=True)

        # 3. Group all items by store, preserving bucket assignment
        stores_dict: dict[str, list[dict]] = {}
        for item in items:
            store_name = item.get("store_name", "Unknown")
            if store_name not in stores_dict:
                stores_dict[store_name] = []
            stores_dict[store_name].append({
                "item_key": item.get("item_key"),
                "brand": item.get("brand", ""),
                "product_name": item.get("display_name", ""),
                "original_price": item.get("original_price", 0),
                "promo_price": item.get("promo_price", 0),
                "savings": item.get("savings_amount") or item.get("savings", 0),
                "discount_percentage": item.get("discount_percentage", 0),
                "mechanism": item.get("display_mechanism", ""),
                "validity_start": item.get("validity_start", ""),
                "validity_end": item.get("validity_end", ""),
                "promo_folder_url": item.get("promo_folder_url"),
                "display_name": item.get("display_name", ""),
                "display_mechanism": item.get("display_mechanism", ""),
                "display_description": item.get("display_description", ""),
                "display_unit_price": item.get("display_unit_price"),
                "display_savings_label": item.get("display_savings_label"),
                "savings_amount": item.get("savings_amount", 0),
                "min_purchase_qty": item.get("min_purchase_qty", 1),
                "effective_unit_price": item.get("effective_unit_price"),
                "bucket": item.get("bucket", ""),
                "bucket_label": item.get("bucket_label", ""),
            })

        stores = []
        for store_name, store_items in stores_dict.items():
            total_savings = round(sum(i.get("savings", 0) for i in store_items), 2)
            validity_end = max(
                (i.get("validity_end", "") for i in store_items),
                default="",
            )
            stores.append({
                "store_name": store_name,
                "total_savings": total_savings,
                "validity_end": validity_end,
                "items": store_items,
            })

        # Sort stores by preferred_stores order (array index = display order)
        if preferred_stores:
            store_order = {(resolve_store_name(name) or name.lower()): i for i, name in enumerate(preferred_stores)}
            stores.sort(key=lambda s: store_order.get(s["store_name"].lower(), len(preferred_stores)))
        else:
            stores.sort(key=lambda s: s["total_savings"], reverse=True)

        # 6. Compute summary
        all_savings = [i.get("savings", 0) for i in items]
        total_savings = round(sum(all_savings), 2)
        deal_count = len(items)

        stores_breakdown = []
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
        # Sort breakdown to match store display order
        if preferred_stores:
            store_order = {(resolve_store_name(name) or name.lower()): i for i, name in enumerate(preferred_stores)}
            stores_breakdown.sort(key=lambda x: store_order.get(x["store"].lower(), len(preferred_stores)))
        else:
            stores_breakdown.sort(key=lambda x: x["savings"], reverse=True)

        best_value = stores_breakdown[0] if stores_breakdown else None

        summary = {
            "total_items": deal_count,
            "total_savings": total_savings,
            "stores_breakdown": stores_breakdown,
            "best_value_store": best_value["store"] if best_value else None,
            "best_value_savings": best_value["savings"] if best_value else 0,
            "best_value_items": best_value["items"] if best_value else 0,
        }

        return {
            "report_id": candidates_row.id,
            "report_status": PromoReportStatus.READY.value,
            "message": "Your weekly deals are ready." if deal_count > 0 else "No active deals matched your habits this week.",
            "generated_at": candidates_row.generated_at.isoformat() if candidates_row.generated_at else None,
            "weekly_savings": total_savings,
            "deal_count": deal_count,
            "promo_week": promo_week,
            "stores": stores,
            "preferred_stores": canonical_preferred if preferred_stores else [],
            "summary": summary,
        }
