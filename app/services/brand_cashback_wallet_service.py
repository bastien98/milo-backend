from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.brand_cashback_balance_repo import (
    BrandCashbackBalanceRepository,
)
from app.db.repositories.brand_cashback_repo import BrandCashbackRepository
from app.models.brand_cashback import BrandCashbackEarning
from app.schemas.brand_cashback import (
    BrandCashbackEarningEvent,
    BrandCashbackWalletResponse,
)
from app.services.brand_cashback_service import image_url_for_key


def _earning_to_event(earning: BrandCashbackEarning) -> BrandCashbackEarningEvent:
    """Map the joined earning row → wire response. Campaign must be eagerly loaded."""
    campaign = earning.campaign
    return BrandCashbackEarningEvent(
        id=earning.id,
        campaign_id=earning.campaign_id,
        brand_name=campaign.brand_name if campaign else "",
        product_name=campaign.product_name if campaign else "",
        image_thumb_url=image_url_for_key(campaign.image_thumb_s3_key) if campaign else None,
        cashback_earned_cents=earning.cashback_earned_cents,
        earned_at=earning.earned_at,
        receipt_id=earning.receipt_id,
    )


class BrandCashbackWalletService:
    """Read-side aggregation for the wallet. Writes (credit/debit) are the
    responsibility of brand_cashback_service and withdrawal_service."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.bc_repo = BrandCashbackRepository(db)
        self.balance_repo = BrandCashbackBalanceRepository(db)

    async def get_wallet(
        self, user_id: str, *, earnings_limit: int = 50
    ) -> BrandCashbackWalletResponse:
        balance = await self.balance_repo.get_balance(user_id)
        earnings = await self.bc_repo.list_earnings_for_user(
            user_id, limit=earnings_limit, offset=0
        )
        return BrandCashbackWalletResponse(
            balance_cents=balance.balance_cents,
            total_earned_cents=balance.total_earned_cents,
            total_withdrawn_cents=balance.total_withdrawn_cents,
            recent_earnings=[_earning_to_event(e) for e in earnings],
        )
