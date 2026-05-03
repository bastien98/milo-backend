import logging
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.brand_cashback_repo import BrandCashbackRepository
from app.db.repositories.cashback_repo import CashbackRepository
from app.models.brand_cashback import BrandCashbackCampaign, UserBrandCashbackClaim
from app.schemas.brand_cashback import BrandCashbackDealResponse
from app.services.storage_service import StorageService

logger = logging.getLogger(__name__)

FUZZY_THRESHOLD = 0.85

storage = StorageService()


def image_url_for_key(key: Optional[str]) -> Optional[str]:
    """Generate a fresh presigned URL for a campaign image S3 key, or None."""
    if not key:
        return None
    return storage.generate_presigned_url(key)


def _is_line_item_match(receipt_item: str, known_item: str) -> bool:
    """Case-insensitive exact match, then fuzzy fallback (SequenceMatcher ≥ 0.85)."""
    a, b = receipt_item.upper().strip(), known_item.upper().strip()
    if a == b:
        return True
    return SequenceMatcher(None, a, b).ratio() >= FUZZY_THRESHOLD


def campaign_to_deal_response(
    campaign: BrandCashbackCampaign,
    user_status: str,
    *,
    current_redemptions: int = 0,
    eligible_skus: Optional[list[str]] = None,
    claim_expires_at: Optional[datetime] = None,
    earned_at: Optional[datetime] = None,
) -> BrandCashbackDealResponse:
    return BrandCashbackDealResponse(
        id=campaign.id,
        brand_name=campaign.brand_name,
        product_name=campaign.product_name,
        description=campaign.description,
        cashback_amount=campaign.cashback_amount_cents / 100,
        image_url=image_url_for_key(campaign.image_s3_key),
        valid_from=campaign.valid_from,
        valid_until=campaign.valid_until,
        eligible_stores=campaign.eligible_stores or [],
        requires_store=campaign.requires_store,
        user_status=user_status,
        earned_at=earned_at,
        terms=campaign.terms,
        how_it_works=campaign.how_it_works or [],
        claim_window_days=campaign.claim_window_days,
        max_redemptions_per_user=campaign.max_redemptions_per_user,
        total_redemption_cap=campaign.total_redemption_cap,
        category=campaign.category,
        featured=campaign.featured,
        current_redemptions=current_redemptions,
        eligible_skus=eligible_skus or [],
        claim_expires_at=claim_expires_at,
    )


class BrandCashbackService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = BrandCashbackRepository(db)

    # ------------------------------------------------------------------
    # User-facing
    # ------------------------------------------------------------------

    async def get_deals_for_user(self, user_id: str) -> list[BrandCashbackDealResponse]:
        """Active campaigns, each annotated with the user's personal status."""
        campaigns = await self.repo.get_active_campaigns()
        claims = await self.repo.get_user_claims(user_id)

        now = datetime.now(timezone.utc)
        result = []
        for campaign in campaigns:
            claim = claims.get(campaign.id)
            if claim:
                user_status = claim.status  # "claimed" | "earned"
            elif campaign.valid_until < now:
                user_status = "expired"
            else:
                user_status = "available"

            # Exclude earned deals — they vanish from the UI after overlay dismissed
            if user_status == "earned":
                continue

            _, earned_count = await self.repo.get_campaign_claim_counts(campaign.id)
            eligible_skus = await self.repo.get_distinct_exact_line_items(campaign.id)
            claim_expires_at = None
            if claim and claim.status == "claimed":
                claim_expires_at = claim.claimed_at + timedelta(
                    days=campaign.claim_window_days
                )

            result.append(
                campaign_to_deal_response(
                    campaign,
                    user_status,
                    current_redemptions=earned_count,
                    eligible_skus=eligible_skus,
                    claim_expires_at=claim_expires_at,
                )
            )
        return result

    async def claim_deal(
        self, user_id: str, campaign_id: str
    ) -> tuple[Optional[UserBrandCashbackClaim], Optional[str]]:
        """Idempotent claim with cap enforcement.

        Returns (claim, error). On success, error is None. On failure, claim is None
        and error is one of: "not_found", "user_limit_reached", "campaign_full".
        """
        campaign = await self.repo.get_campaign_by_id(campaign_id)
        if not campaign or not campaign.is_active:
            return None, "not_found"

        # Idempotent: already a pending claim → return it untouched.
        existing = await self.repo.get_active_claim(user_id, campaign_id)
        if existing:
            return existing, None

        # Per-user cap (counts both pending and earned rows).
        user_count = await self.repo.count_user_claims_for_campaign(user_id, campaign_id)
        if user_count >= campaign.max_redemptions_per_user:
            return None, "user_limit_reached"

        # Total redemption cap (counts only earned, since unredeemed claims don't lock supply).
        if campaign.total_redemption_cap is not None:
            _, earned = await self.repo.get_campaign_claim_counts(campaign_id)
            if earned >= campaign.total_redemption_cap:
                return None, "campaign_full"

        return await self.repo.create_claim(user_id, campaign_id), None

    async def unclaim_deal(self, user_id: str, campaign_id: str) -> bool:
        """Remove a claim only if still in 'claimed' status."""
        return await self.repo.delete_claim(user_id, campaign_id)

    # ------------------------------------------------------------------
    # Receipt matching (called from receipt_background_worker)
    # ------------------------------------------------------------------

    async def check_receipt_for_brand_cashback(
        self,
        receipt_id: str,
        user_id: str,
        receipt_line_items: list[str],
        store_name: Optional[str],
    ) -> int:
        """
        For each 'claimed' deal the user has, try to find a matching line item
        on the receipt. On match, mark the claim as earned and credit the user's
        Milo Points wallet.
        """
        pending_claims = await self.repo.get_user_claimed_claims(user_id)
        if not pending_claims:
            return 0

        earned_count = 0

        cashback_repo = CashbackRepository(self.db)

        now = datetime.now(timezone.utc)

        for claim in pending_claims:
            campaign = claim.campaign
            if not campaign or not campaign.is_active:
                continue

            # Enforce claim window: receipt upload must be within
            # claim_window_days of the original claim.
            window_end = claim.claimed_at + timedelta(days=campaign.claim_window_days)
            if now > window_end:
                logger.info(
                    f"Brand cashback: claim {claim.id} expired "
                    f"(claimed_at={claim.claimed_at} window={campaign.claim_window_days}d) — skipping"
                )
                continue

            # Enforce total_redemption_cap (race-condition guard:
            # cap was enforced at claim time, but earned count may have grown since).
            if campaign.total_redemption_cap is not None:
                _, earned_so_far = await self.repo.get_campaign_claim_counts(campaign.id)
                if earned_so_far >= campaign.total_redemption_cap:
                    logger.info(
                        f"Brand cashback: campaign {campaign.id} full "
                        f"({earned_so_far}/{campaign.total_redemption_cap}) — skipping match"
                    )
                    continue

            # Check store eligibility
            if campaign.requires_store:
                if not store_name:
                    continue
                eligible = [s.lower() for s in (campaign.eligible_stores or [])]
                if store_name.lower() not in eligible:
                    continue
                line_items = await self.repo.get_line_items_for_campaign_store(
                    campaign.id, store_name
                )
            else:
                # All-store deal: gather all known line items across stores
                line_items = await self.repo.get_line_items_for_campaign(campaign.id)

            if not line_items:
                logger.debug(
                    f"Brand cashback: no line items configured for campaign {campaign.id} "
                    f"at store '{store_name}' — skipping"
                )
                continue

            # Build full list of known strings (exact + alt spellings)
            known_strings: list[tuple[str, str]] = []  # (line_item_id, known_string)
            for li in line_items:
                known_strings.append((li.id, li.exact_line_item))
                for alt in (li.alt_line_items or []):
                    known_strings.append((li.id, alt))

            # Try to match any receipt item against known strings
            matched_line_item_id: Optional[str] = None
            for receipt_item in receipt_line_items:
                for li_id, known in known_strings:
                    if _is_line_item_match(receipt_item, known):
                        matched_line_item_id = li_id
                        break
                if matched_line_item_id:
                    break

            if not matched_line_item_id:
                continue

            # Mark claim as earned
            await self.repo.mark_claim_earned(
                claim_id=claim.id,
                receipt_id=receipt_id,
                matched_line_item_id=matched_line_item_id,
                cashback_earned_cents=campaign.cashback_amount_cents,
            )

            # Credit Milo Points wallet (1 point per cent, same as POINTS_PER_EURO=1000)
            # 50 cents = 500 points = €0.50
            points_to_award = campaign.cashback_amount_cents * 10
            await cashback_repo.upsert_points_increment(user_id, points_to_award)
            earned_count += 1

            logger.info(
                f"Brand cashback earned: user={user_id} campaign={campaign.id} "
                f"store='{store_name}' amount_cents={campaign.cashback_amount_cents}"
            )

        return earned_count
