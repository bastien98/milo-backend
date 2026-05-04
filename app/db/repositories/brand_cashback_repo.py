import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, func, update, delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.brand_cashback import (
    BrandCashbackCampaign,
    BrandCashbackClaim,
    BrandCashbackCodeProposal,
    BrandCashbackEarning,
    BrandCashbackPendingMatch,
    BrandCashbackStoreLineItem,
)


class BrandCashbackRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ------------------------------------------------------------------
    # Campaigns
    # ------------------------------------------------------------------

    async def get_active_campaigns(self) -> list[BrandCashbackCampaign]:
        """Active campaigns currently within their valid window (not scheduled, not expired)."""
        now = datetime.now(timezone.utc)
        result = await self.db.execute(
            select(BrandCashbackCampaign)
            .where(
                BrandCashbackCampaign.is_active == True,
                BrandCashbackCampaign.valid_from <= now,
                BrandCashbackCampaign.valid_until > now,
            )
            .order_by(BrandCashbackCampaign.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_all_campaigns(
        self, include_inactive: bool = False
    ) -> list[BrandCashbackCampaign]:
        """All campaigns (admin). Hides soft-deleted (`is_active=false`) by default."""
        stmt = select(BrandCashbackCampaign).order_by(
            BrandCashbackCampaign.created_at.desc()
        )
        if not include_inactive:
            stmt = stmt.where(BrandCashbackCampaign.is_active == True)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_campaign_by_id(self, campaign_id: str) -> Optional[BrandCashbackCampaign]:
        result = await self.db.execute(
            select(BrandCashbackCampaign).where(BrandCashbackCampaign.id == campaign_id)
        )
        return result.scalar_one_or_none()

    async def create_campaign(self, data: dict) -> BrandCashbackCampaign:
        campaign = BrandCashbackCampaign(**data)
        self.db.add(campaign)
        await self.db.flush()
        return campaign

    async def update_campaign(self, campaign_id: str, data: dict) -> Optional[BrandCashbackCampaign]:
        await self.db.execute(
            update(BrandCashbackCampaign)
            .where(BrandCashbackCampaign.id == campaign_id)
            .values(**data)
        )
        await self.db.flush()
        return await self.get_campaign_by_id(campaign_id)

    async def delete_campaign(self, campaign_id: str) -> None:
        await self.db.execute(
            delete(BrandCashbackCampaign).where(BrandCashbackCampaign.id == campaign_id)
        )
        await self.db.flush()

    # ------------------------------------------------------------------
    # Line Items
    # ------------------------------------------------------------------

    async def get_distinct_exact_line_items(self, campaign_id: str) -> list[str]:
        """Distinct `exact_line_item` strings across the campaign — surfaced to iOS as eligible SKUs."""
        result = await self.db.execute(
            select(BrandCashbackStoreLineItem.exact_line_item)
            .where(BrandCashbackStoreLineItem.campaign_id == campaign_id)
            .distinct()
            .order_by(BrandCashbackStoreLineItem.exact_line_item)
        )
        return [row for row in result.scalars().all()]

    async def get_line_items_for_campaign(
        self, campaign_id: str
    ) -> list[BrandCashbackStoreLineItem]:
        result = await self.db.execute(
            select(BrandCashbackStoreLineItem)
            .where(BrandCashbackStoreLineItem.campaign_id == campaign_id)
            .order_by(BrandCashbackStoreLineItem.store_name)
        )
        return list(result.scalars().all())

    async def get_line_items_for_campaign_store(
        self, campaign_id: str, store_name: str
    ) -> list[BrandCashbackStoreLineItem]:
        result = await self.db.execute(
            select(BrandCashbackStoreLineItem).where(
                BrandCashbackStoreLineItem.campaign_id == campaign_id,
                func.lower(BrandCashbackStoreLineItem.store_name) == store_name.lower(),
            )
        )
        return list(result.scalars().all())

    async def find_line_items_by_code(
        self,
        code: str,
        campaign_id: str,
        store_name: Optional[str] = None,
    ) -> list[BrandCashbackStoreLineItem]:
        """Line items whose product_codes JSONB array contains `code`.

        Uses the GIN index on product_codes via a containment query.
        When store_name is provided, the result is also store-scoped
        (case-insensitive) — used for code-required campaigns.
        """
        stmt = select(BrandCashbackStoreLineItem).where(
            BrandCashbackStoreLineItem.campaign_id == campaign_id,
            BrandCashbackStoreLineItem.product_codes.contains([code]),
        )
        if store_name is not None:
            stmt = stmt.where(
                func.lower(BrandCashbackStoreLineItem.store_name) == store_name.lower()
            )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_line_item_by_id(self, line_item_id: str) -> Optional[BrandCashbackStoreLineItem]:
        result = await self.db.execute(
            select(BrandCashbackStoreLineItem).where(
                BrandCashbackStoreLineItem.id == line_item_id
            )
        )
        return result.scalar_one_or_none()

    async def create_line_item(self, data: dict) -> BrandCashbackStoreLineItem:
        item = BrandCashbackStoreLineItem(**data)
        self.db.add(item)
        await self.db.flush()
        return item

    async def update_line_item(self, line_item_id: str, data: dict) -> Optional[BrandCashbackStoreLineItem]:
        await self.db.execute(
            update(BrandCashbackStoreLineItem)
            .where(BrandCashbackStoreLineItem.id == line_item_id)
            .values(**data)
        )
        await self.db.flush()
        return await self.get_line_item_by_id(line_item_id)

    async def delete_line_item(self, line_item_id: str) -> None:
        await self.db.execute(
            delete(BrandCashbackStoreLineItem).where(
                BrandCashbackStoreLineItem.id == line_item_id
            )
        )
        await self.db.flush()

    async def add_product_codes(self, line_item_id: str, codes: list[str]) -> int:
        """Append digit-only codes to a line item's product_codes JSONB array.

        Used by the matcher's auto-extend path: when a Tier 2 (text exact) match
        fires and the receipt brought codes that aren't yet on the line item,
        append them so future receipts with the new SKU hit Tier 1 directly.

        Idempotent — codes already present (after digit normalisation) are skipped.
        Codes failing the digits-only / length 4-14 filter are silently dropped.

        Returns the number of codes actually added.
        """
        if not codes:
            return 0
        item = await self.get_line_item_by_id(line_item_id)
        if item is None:
            return 0
        existing = set(item.product_codes or [])
        added: list[str] = []
        for raw in codes:
            digits = "".join(ch for ch in (raw or "") if ch.isdigit())
            if not (4 <= len(digits) <= 14):
                continue
            if digits in existing or digits in added:
                continue
            added.append(digits)
        if not added:
            return 0
        new_codes = list(item.product_codes or []) + added
        await self.db.execute(
            update(BrandCashbackStoreLineItem)
            .where(BrandCashbackStoreLineItem.id == line_item_id)
            .values(product_codes=new_codes)
        )
        await self.db.flush()
        return len(added)

    async def add_alt_line_item(self, line_item_id: str, alt_string: str) -> None:
        """Append `alt_string` to a line item's alt_line_items JSONB array.

        No-op if the string (after .strip().upper() normalization) is already
        present as either the exact_line_item or any existing alt. Idempotent.
        """
        item = await self.get_line_item_by_id(line_item_id)
        if item is None:
            return
        norm = alt_string.strip().upper()
        existing_norm = {item.exact_line_item.strip().upper()} | {
            (a or "").strip().upper() for a in (item.alt_line_items or [])
        }
        if norm in existing_norm:
            return
        new_alts = list(item.alt_line_items or []) + [alt_string]
        await self.db.execute(
            update(BrandCashbackStoreLineItem)
            .where(BrandCashbackStoreLineItem.id == line_item_id)
            .values(alt_line_items=new_alts)
        )
        await self.db.flush()

    # ------------------------------------------------------------------
    # Claims (persistent intent)
    # ------------------------------------------------------------------

    async def get_user_claim(
        self, user_id: str, campaign_id: str
    ) -> Optional[BrandCashbackClaim]:
        result = await self.db.execute(
            select(BrandCashbackClaim).where(
                BrandCashbackClaim.user_id == user_id,
                BrandCashbackClaim.campaign_id == campaign_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_user_claims_by_campaign(
        self, user_id: str
    ) -> dict[str, BrandCashbackClaim]:
        """Map of campaign_id -> claim for the user. UNIQUE(user_id, campaign_id)
        guarantees at most one row per pair."""
        result = await self.db.execute(
            select(BrandCashbackClaim).where(BrandCashbackClaim.user_id == user_id)
        )
        return {c.campaign_id: c for c in result.scalars().all()}

    async def get_user_claims_with_campaigns(
        self, user_id: str
    ) -> list[BrandCashbackClaim]:
        """All claims for a user, with the campaign eagerly loaded.

        Used by read-side surfaces (`/deals`, `/my-claims`, `_resolve_user_status`,
        `claim_deal`) that need to see capped claims too — to render "earned"
        cards, reject re-claims with 409, etc. The matcher uses
        `get_active_claims_for_matching` instead, which filters out capped
        claims pre-emptively.
        """
        result = await self.db.execute(
            select(BrandCashbackClaim)
            .options(selectinload(BrandCashbackClaim.campaign))
            .where(BrandCashbackClaim.user_id == user_id)
        )
        return list(result.scalars().all())

    async def get_active_claims_for_matching(
        self, user_id: str
    ) -> list[BrandCashbackClaim]:
        """Claims the matcher should evaluate on a new receipt.

        Filters out claims where the user has already reached the campaign's
        per-user cap. The cap is computed via a correlated subquery on
        `BrandCashbackEarning` so we get one round-trip (no N+1 COUNTs) and
        the result auto-revives if `max_redemptions_per_user` is later raised
        — there's no persistent "consumed" flag on the claim row to keep in
        sync.

        Mirrors `get_user_claims_with_campaigns`'s eager-load of the campaign
        so the matcher loop can read `claim.campaign.*` without lazy-loading.
        """
        earnings_count = (
            select(func.count(BrandCashbackEarning.id))
            .where(
                BrandCashbackEarning.user_id == BrandCashbackClaim.user_id,
                BrandCashbackEarning.campaign_id == BrandCashbackClaim.campaign_id,
            )
            .correlate(BrandCashbackClaim)
            .scalar_subquery()
        )

        stmt = (
            select(BrandCashbackClaim)
            .options(selectinload(BrandCashbackClaim.campaign))
            .join(
                BrandCashbackCampaign,
                BrandCashbackCampaign.id == BrandCashbackClaim.campaign_id,
            )
            .where(
                BrandCashbackClaim.user_id == user_id,
                earnings_count < BrandCashbackCampaign.max_redemptions_per_user,
            )
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def upsert_claim(
        self, user_id: str, campaign_id: str
    ) -> BrandCashbackClaim:
        """Idempotent claim insert. Returns the existing or newly-created row."""
        stmt = (
            pg_insert(BrandCashbackClaim)
            .values(
                id=str(uuid.uuid4()),
                user_id=user_id,
                campaign_id=campaign_id,
            )
            .on_conflict_do_nothing(
                constraint="uq_brand_cashback_claims_user_campaign"
            )
        )
        await self.db.execute(stmt)
        await self.db.flush()
        # Re-read to return the canonical row (whether just inserted or pre-existing).
        existing = await self.get_user_claim(user_id, campaign_id)
        assert existing is not None
        return existing

    async def delete_claim(self, user_id: str, campaign_id: str) -> bool:
        """Delete the user's claim. Returns True if a row was removed."""
        result = await self.db.execute(
            delete(BrandCashbackClaim).where(
                BrandCashbackClaim.user_id == user_id,
                BrandCashbackClaim.campaign_id == campaign_id,
            )
        )
        await self.db.flush()
        return (result.rowcount or 0) > 0

    # ------------------------------------------------------------------
    # Earnings (match events)
    # ------------------------------------------------------------------

    async def count_user_earnings_for_campaign(
        self, user_id: str, campaign_id: str
    ) -> int:
        result = await self.db.execute(
            select(func.count()).where(
                BrandCashbackEarning.user_id == user_id,
                BrandCashbackEarning.campaign_id == campaign_id,
            )
        )
        return result.scalar() or 0

    async def count_earnings_for_campaign(self, campaign_id: str) -> int:
        result = await self.db.execute(
            select(func.count()).where(
                BrandCashbackEarning.campaign_id == campaign_id,
            )
        )
        return result.scalar() or 0

    async def get_user_earnings_by_campaign(
        self, user_id: str
    ) -> dict[str, list[BrandCashbackEarning]]:
        """Group all of a user's earnings by campaign_id (newest first within each)."""
        result = await self.db.execute(
            select(BrandCashbackEarning)
            .where(BrandCashbackEarning.user_id == user_id)
            .order_by(BrandCashbackEarning.earned_at.desc())
        )
        out: dict[str, list[BrandCashbackEarning]] = {}
        for e in result.scalars().all():
            out.setdefault(e.campaign_id, []).append(e)
        return out

    async def sum_earnings_for_user(self, user_id: str) -> int:
        """Total cents the user has ever earned from brand cashback. 0 for users
        with no earnings."""
        result = await self.db.execute(
            select(
                func.coalesce(func.sum(BrandCashbackEarning.cashback_earned_cents), 0)
            ).where(BrandCashbackEarning.user_id == user_id)
        )
        return result.scalar() or 0

    async def list_earnings_for_user(
        self, user_id: str, limit: int = 50, offset: int = 0
    ) -> list[BrandCashbackEarning]:
        """Earnings feed for the wallet, newest first, with the campaign eagerly
        loaded so each row can render brand + product + thumbnail without N+1 reads."""
        result = await self.db.execute(
            select(BrandCashbackEarning)
            .options(selectinload(BrandCashbackEarning.campaign))
            .where(BrandCashbackEarning.user_id == user_id)
            .order_by(BrandCashbackEarning.earned_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def create_earning(
        self,
        user_id: str,
        campaign_id: str,
        receipt_id: str,
        matched_line_item_id: str,
        cashback_earned_cents: int,
    ) -> BrandCashbackEarning:
        earning = BrandCashbackEarning(
            id=str(uuid.uuid4()),
            user_id=user_id,
            campaign_id=campaign_id,
            receipt_id=receipt_id,
            matched_line_item_id=matched_line_item_id,
            cashback_earned_cents=cashback_earned_cents,
            earned_at=datetime.now(timezone.utc),
        )
        self.db.add(earning)
        await self.db.flush()
        return earning

    # ------------------------------------------------------------------
    # Pending matches (manual review queue)
    # ------------------------------------------------------------------

    async def create_pending_match(
        self,
        *,
        user_id: str,
        campaign_id: str,
        receipt_id: str,
        candidate_string: str,
        matched_line_item_id: Optional[str],
        match_score: float,
        store_name: Optional[str],
    ) -> Optional[BrandCashbackPendingMatch]:
        """Idempotent insert; returns existing row if (user, campaign, receipt) collides."""
        stmt = (
            pg_insert(BrandCashbackPendingMatch)
            .values(
                id=str(uuid.uuid4()),
                user_id=user_id,
                campaign_id=campaign_id,
                receipt_id=receipt_id,
                candidate_string=candidate_string,
                matched_line_item_id=matched_line_item_id,
                match_score=match_score,
                store_name=store_name,
            )
            .on_conflict_do_nothing(
                constraint="uq_brand_cashback_pending_user_campaign_receipt"
            )
        )
        await self.db.execute(stmt)
        await self.db.flush()
        # Re-read so the caller gets the canonical row whether we inserted or hit the conflict.
        result = await self.db.execute(
            select(BrandCashbackPendingMatch).where(
                BrandCashbackPendingMatch.user_id == user_id,
                BrandCashbackPendingMatch.campaign_id == campaign_id,
                BrandCashbackPendingMatch.receipt_id == receipt_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_pending_match(self, pending_id: str) -> Optional[BrandCashbackPendingMatch]:
        """Single fetch with all relations admin response needs eagerly loaded.

        `_pending_to_response(..., include_admin_context=True)` reads
        `p.receipt.storage_key` (for the receipt thumbnail URL) — without
        eager-load that triggers an async lazy-load and crashes the request
        post-approval, rolling the approve back. Always include `receipt` and
        `user` so the response serialiser is async-safe.
        """
        result = await self.db.execute(
            select(BrandCashbackPendingMatch)
            .options(
                selectinload(BrandCashbackPendingMatch.campaign),
                selectinload(BrandCashbackPendingMatch.matched_line_item),
                selectinload(BrandCashbackPendingMatch.receipt),
                selectinload(BrandCashbackPendingMatch.user),
            )
            .where(BrandCashbackPendingMatch.id == pending_id)
        )
        return result.scalar_one_or_none()

    async def get_pending_matches_for_user(
        self, user_id: str, status: str = "pending"
    ) -> list[BrandCashbackPendingMatch]:
        result = await self.db.execute(
            select(BrandCashbackPendingMatch)
            .where(
                BrandCashbackPendingMatch.user_id == user_id,
                BrandCashbackPendingMatch.status == status,
            )
            .order_by(BrandCashbackPendingMatch.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_recent_denials_for_user(
        self, user_id: str, since: datetime
    ) -> list[BrandCashbackPendingMatch]:
        """Denied reviews newer than `since`, used for the 7-day in-app banner."""
        result = await self.db.execute(
            select(BrandCashbackPendingMatch)
            .where(
                BrandCashbackPendingMatch.user_id == user_id,
                BrandCashbackPendingMatch.status == "denied",
                BrandCashbackPendingMatch.reviewed_at >= since,
            )
            .order_by(BrandCashbackPendingMatch.reviewed_at.desc())
        )
        return list(result.scalars().all())

    async def get_pending_matches_for_admin(
        self, status: Optional[str]
    ) -> list[BrandCashbackPendingMatch]:
        stmt = select(BrandCashbackPendingMatch).options(
            selectinload(BrandCashbackPendingMatch.campaign),
            selectinload(BrandCashbackPendingMatch.matched_line_item),
            selectinload(BrandCashbackPendingMatch.user),
            selectinload(BrandCashbackPendingMatch.receipt),
        )
        if status and status != "all":
            stmt = stmt.where(BrandCashbackPendingMatch.status == status)
        stmt = stmt.order_by(BrandCashbackPendingMatch.created_at.desc())
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def count_pending(self) -> int:
        result = await self.db.execute(
            select(func.count()).where(BrandCashbackPendingMatch.status == "pending")
        )
        return result.scalar() or 0

    async def lock_pending_match(self, pending_id: str) -> Optional[BrandCashbackPendingMatch]:
        """SELECT … FOR UPDATE to serialise concurrent admin clicks on the same row.

        Eagerly loads `campaign` and `receipt` because `approve_pending_match`
        re-checks campaign activity / window plus the receipt's date — accessing
        either via lazy-load post-FOR-UPDATE would crash in async SQLAlchemy.
        """
        result = await self.db.execute(
            select(BrandCashbackPendingMatch)
            .options(
                selectinload(BrandCashbackPendingMatch.campaign),
                selectinload(BrandCashbackPendingMatch.receipt),
            )
            .where(BrandCashbackPendingMatch.id == pending_id)
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def lock_campaign_for_cap_check(self, campaign_id: str) -> None:
        """SELECT ... FOR UPDATE on a campaign row to serialise the
        total_redemption_cap check across users.

        Two different users hitting the last cap slot would otherwise both
        observe `count < cap` and both create earnings, exceeding the cap by 1.
        Holding this row lock through the COUNT + create_earning ensures one
        user wins, the other re-reads count and gets blocked. Lock auto-releases
        at COMMIT — the matcher's caller commits after each receipt finishes.

        Only call when `campaign.total_redemption_cap is not None` — for
        uncapped campaigns it's pure overhead.
        """
        await self.db.execute(
            select(BrandCashbackCampaign.id)
            .where(BrandCashbackCampaign.id == campaign_id)
            .with_for_update()
        )

    async def mark_pending_approved(
        self, pending_id: str, reviewer_id: str, earning_id: str
    ) -> None:
        await self.db.execute(
            update(BrandCashbackPendingMatch)
            .where(BrandCashbackPendingMatch.id == pending_id)
            .values(
                status="approved",
                reviewed_at=datetime.now(timezone.utc),
                reviewed_by=reviewer_id,
                earning_id=earning_id,
            )
        )
        await self.db.flush()

    async def mark_pending_denied(
        self, pending_id: str, reviewer_id: str, reason: str
    ) -> None:
        await self.db.execute(
            update(BrandCashbackPendingMatch)
            .where(BrandCashbackPendingMatch.id == pending_id)
            .values(
                status="denied",
                reviewed_at=datetime.now(timezone.utc),
                reviewed_by=reviewer_id,
                denial_reason=reason,
            )
        )
        await self.db.flush()

    # ------------------------------------------------------------------
    # Admin stats
    # ------------------------------------------------------------------

    async def get_campaign_claim_counts(self, campaign_id: str) -> tuple[int, int]:
        """Returns (claims_count, earnings_count) for the campaign."""
        claims_result = await self.db.execute(
            select(func.count()).where(BrandCashbackClaim.campaign_id == campaign_id)
        )
        earnings_result = await self.db.execute(
            select(func.count()).where(BrandCashbackEarning.campaign_id == campaign_id)
        )
        return (claims_result.scalar() or 0, earnings_result.scalar() or 0)

    async def get_global_stats(self) -> dict:
        now = datetime.now(timezone.utc)

        active_count_result = await self.db.execute(
            select(func.count()).where(
                BrandCashbackCampaign.is_active == True,
                BrandCashbackCampaign.valid_until > now,
            )
        )
        total_claims_result = await self.db.execute(
            select(func.count(BrandCashbackClaim.id))
        )
        earnings_result = await self.db.execute(
            select(
                func.count(BrandCashbackEarning.id),
                func.coalesce(func.sum(BrandCashbackEarning.cashback_earned_cents), 0),
            )
        )
        earnings_row = earnings_result.one()

        avg_result = await self.db.execute(
            select(func.avg(BrandCashbackCampaign.cashback_amount_cents)).where(
                BrandCashbackCampaign.is_active == True
            )
        )

        return {
            "total_active_campaigns": active_count_result.scalar() or 0,
            "total_claims": total_claims_result.scalar() or 0,
            "total_earned_claims": earnings_row[0] or 0,
            "total_earned_euros": (earnings_row[1] or 0) / 100,
            "avg_cashback_euros": (avg_result.scalar() or 0) / 100,
        }


    # ------------------------------------------------------------------
    # Code-extension proposals (admin-reviewed alternative to auto-extend)
    # ------------------------------------------------------------------

    async def propose_product_codes(
        self,
        line_item_id: str,
        codes: list[str],
        source_user_id: str,
        source_receipt_id: Optional[str],
    ) -> int:
        """Insert a proposal row per (line_item_id, code) where code isn't
        already on the line item's product_codes. ON CONFLICT DO NOTHING via
        the UNIQUE constraint, so 50 users hitting the same fluke code create
        one proposal in total — first proposer wins source attribution.

        Returns the number of NEW proposal rows inserted.
        """
        if not codes:
            return 0
        item = await self.get_line_item_by_id(line_item_id)
        if item is None:
            return 0
        existing_on_line_item = set(item.product_codes or [])
        rows = []
        for code in codes:
            digits = "".join(ch for ch in (code or "") if ch.isdigit())
            if not (4 <= len(digits) <= 14):
                continue
            if digits in existing_on_line_item:
                continue
            rows.append(
                {
                    "id": str(uuid.uuid4()),
                    "line_item_id": line_item_id,
                    "code": digits,
                    "source_user_id": source_user_id,
                    "source_receipt_id": source_receipt_id,
                }
            )
        if not rows:
            return 0
        stmt = (
            pg_insert(BrandCashbackCodeProposal)
            .values(rows)
            .on_conflict_do_nothing(constraint="uq_code_proposals_line_item_code")
        )
        result = await self.db.execute(stmt)
        await self.db.flush()
        return int(result.rowcount or 0)

    async def get_pending_code_proposals(
        self,
    ) -> list[BrandCashbackCodeProposal]:
        """Admin list — pending only, eager-load line item + campaign + receipt
        + source user so the response serializer doesn't lazy-load."""
        result = await self.db.execute(
            select(BrandCashbackCodeProposal)
            .options(
                selectinload(BrandCashbackCodeProposal.line_item).selectinload(
                    BrandCashbackStoreLineItem.campaign
                ),
            )
            .where(BrandCashbackCodeProposal.status == "pending")
            .order_by(BrandCashbackCodeProposal.proposed_at.desc())
        )
        return list(result.scalars().all())

    async def get_code_proposal(
        self, proposal_id: str
    ) -> Optional[BrandCashbackCodeProposal]:
        result = await self.db.execute(
            select(BrandCashbackCodeProposal)
            .options(
                selectinload(BrandCashbackCodeProposal.line_item).selectinload(
                    BrandCashbackStoreLineItem.campaign
                ),
            )
            .where(BrandCashbackCodeProposal.id == proposal_id)
        )
        return result.scalar_one_or_none()

    async def mark_code_proposal_approved(
        self, proposal_id: str, reviewer_id: str
    ) -> None:
        await self.db.execute(
            update(BrandCashbackCodeProposal)
            .where(BrandCashbackCodeProposal.id == proposal_id)
            .values(
                status="approved",
                reviewed_at=datetime.now(timezone.utc),
                reviewed_by=reviewer_id,
            )
        )
        await self.db.flush()

    async def mark_code_proposal_rejected(
        self, proposal_id: str, reviewer_id: str, reason: str
    ) -> None:
        await self.db.execute(
            update(BrandCashbackCodeProposal)
            .where(BrandCashbackCodeProposal.id == proposal_id)
            .values(
                status="rejected",
                reviewed_at=datetime.now(timezone.utc),
                reviewed_by=reviewer_id,
                reject_reason=reason,
            )
        )
        await self.db.flush()
