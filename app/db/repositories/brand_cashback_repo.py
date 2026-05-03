import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, func, update, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.brand_cashback import (
    BrandCashbackCampaign,
    BrandCashbackStoreLineItem,
    UserBrandCashbackClaim,
)


class BrandCashbackRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ------------------------------------------------------------------
    # Campaigns
    # ------------------------------------------------------------------

    async def get_active_campaigns(self) -> list[BrandCashbackCampaign]:
        """Campaigns that are active and not expired."""
        now = datetime.now(timezone.utc)
        result = await self.db.execute(
            select(BrandCashbackCampaign)
            .where(
                BrandCashbackCampaign.is_active == True,
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

    # ------------------------------------------------------------------
    # User Claims
    # ------------------------------------------------------------------

    async def get_user_claims(self, user_id: str) -> dict[str, UserBrandCashbackClaim]:
        """Returns dict keyed by campaign_id for quick lookup."""
        result = await self.db.execute(
            select(UserBrandCashbackClaim).where(UserBrandCashbackClaim.user_id == user_id)
        )
        return {c.campaign_id: c for c in result.scalars().all()}

    async def get_claim(self, user_id: str, campaign_id: str) -> Optional[UserBrandCashbackClaim]:
        result = await self.db.execute(
            select(UserBrandCashbackClaim).where(
                UserBrandCashbackClaim.user_id == user_id,
                UserBrandCashbackClaim.campaign_id == campaign_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_user_claimed_claims(self, user_id: str) -> list[UserBrandCashbackClaim]:
        """All claims still in 'claimed' status (awaiting receipt match)."""
        result = await self.db.execute(
            select(UserBrandCashbackClaim)
            .options(selectinload(UserBrandCashbackClaim.campaign))
            .where(
                UserBrandCashbackClaim.user_id == user_id,
                UserBrandCashbackClaim.status == "claimed",
            )
        )
        return list(result.scalars().all())

    async def create_claim(self, user_id: str, campaign_id: str) -> UserBrandCashbackClaim:
        claim = UserBrandCashbackClaim(
            id=str(uuid.uuid4()),
            user_id=user_id,
            campaign_id=campaign_id,
            status="claimed",
        )
        self.db.add(claim)
        await self.db.flush()
        return claim

    async def delete_claim(self, user_id: str, campaign_id: str) -> bool:
        """Only deletes if status is 'claimed'. Returns True if deleted."""
        claim = await self.get_claim(user_id, campaign_id)
        if claim is None or claim.status != "claimed":
            return False
        await self.db.delete(claim)
        await self.db.flush()
        return True

    async def mark_claim_earned(
        self,
        claim_id: str,
        receipt_id: str,
        matched_line_item_id: str,
        cashback_earned_cents: int,
    ) -> None:
        await self.db.execute(
            update(UserBrandCashbackClaim)
            .where(UserBrandCashbackClaim.id == claim_id)
            .values(
                status="earned",
                receipt_id=receipt_id,
                matched_line_item_id=matched_line_item_id,
                cashback_earned_cents=cashback_earned_cents,
                earned_at=datetime.now(timezone.utc),
            )
        )
        await self.db.flush()

    # ------------------------------------------------------------------
    # Admin stats
    # ------------------------------------------------------------------

    async def get_campaign_claim_counts(self, campaign_id: str) -> tuple[int, int]:
        """Returns (total_claims, earned_claims)."""
        total_result = await self.db.execute(
            select(func.count()).where(UserBrandCashbackClaim.campaign_id == campaign_id)
        )
        earned_result = await self.db.execute(
            select(func.count()).where(
                UserBrandCashbackClaim.campaign_id == campaign_id,
                UserBrandCashbackClaim.status == "earned",
            )
        )
        return (total_result.scalar() or 0, earned_result.scalar() or 0)

    async def get_global_stats(self) -> dict:
        now = datetime.now(timezone.utc)

        active_count_result = await self.db.execute(
            select(func.count()).where(
                BrandCashbackCampaign.is_active == True,
                BrandCashbackCampaign.valid_until > now,
            )
        )
        total_claims_result = await self.db.execute(select(func.count(UserBrandCashbackClaim.id)))
        earned_result = await self.db.execute(
            select(
                func.count(UserBrandCashbackClaim.id),
                func.coalesce(func.sum(UserBrandCashbackClaim.cashback_earned_cents), 0),
            ).where(UserBrandCashbackClaim.status == "earned")
        )
        earned_row = earned_result.one()

        avg_result = await self.db.execute(
            select(func.avg(BrandCashbackCampaign.cashback_amount_cents)).where(
                BrandCashbackCampaign.is_active == True
            )
        )

        return {
            "total_active_campaigns": active_count_result.scalar() or 0,
            "total_claims": total_claims_result.scalar() or 0,
            "total_earned_claims": earned_row[0] or 0,
            "total_earned_euros": (earned_row[1] or 0) / 100,
            "avg_cashback_euros": (avg_result.scalar() or 0) / 100,
        }
