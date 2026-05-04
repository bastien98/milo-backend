import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from difflib import SequenceMatcher
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.brand_cashback_balance_repo import (
    BrandCashbackBalanceRepository,
)
from app.db.repositories.brand_cashback_repo import BrandCashbackRepository
from app.models.brand_cashback import (
    BrandCashbackCampaign,
    BrandCashbackClaim,
    BrandCashbackEarning,
    BrandCashbackPendingMatch,
)


@dataclass(frozen=True)
class ReceiptLineItemForMatching:
    """Minimal projection of a receipt line item used by the brand-cashback matcher.

    `text` is the cleaned item name (case/whitespace will be normalised at compare).
    `codes` is the tuple of every per-line product code (EAN, artikel nummer, PLU)
    that the OCR layer extracted for this line — `dp_article_codes` from the
    extraction pipeline. Empty tuple for chains that don't print codes.

    A campaign line item in code-mode (non-empty product_codes) hits if ANY
    code in this tuple matches ANY code on the line item.
    """

    text: str
    codes: tuple[str, ...] = ()
from app.schemas.brand_cashback import (
    BrandCashbackDealResponse,
    PendingReviewSummary,
    RecentDenialSummary,
)
from app.services.storage_service import StorageService

logger = logging.getLogger(__name__)

# Minimum SequenceMatcher ratio to queue a near-miss for admin review.
# High enough that random unrelated items don't pile up; low enough to catch
# OCR variants (FR/NL spelling, truncation, "PROMO" prefixes).
QUEUE_THRESHOLD = 0.85

# How long a denied review remains visible to the user as "Last receipt: not eligible".
DENIAL_BANNER_TTL = timedelta(days=7)

storage = StorageService()


def image_url_for_key(key: Optional[str]) -> Optional[str]:
    """Generate a fresh presigned URL for an S3 key, or None."""
    if not key:
        return None
    return storage.generate_presigned_url(key)


def _is_line_item_match(receipt_item: str, known_item: str) -> bool:
    """Strict equality after whitespace + case normalization.

    Admins must enter the line-item string exactly as it appears on receipts
    (modulo case/whitespace). No fuzzy matching: a single character difference
    means no match, no reward.
    """
    return receipt_item.strip().upper() == known_item.strip().upper()


def _fuzzy_score(a: str, b: str) -> float:
    return SequenceMatcher(None, a.strip().upper(), b.strip().upper()).ratio()


def _to_pending_summary(p: BrandCashbackPendingMatch) -> PendingReviewSummary:
    return PendingReviewSummary(
        id=p.id,
        receipt_id=p.receipt_id,
        candidate_string=p.candidate_string,
        created_at=p.created_at,
    )


def _to_denial_summary(p: BrandCashbackPendingMatch) -> RecentDenialSummary:
    return RecentDenialSummary(
        id=p.id,
        receipt_id=p.receipt_id,
        denied_at=p.reviewed_at,
        reason=p.denial_reason or "Not eligible",
    )


def campaign_to_deal_response(
    campaign: BrandCashbackCampaign,
    user_status: str,
    *,
    current_redemptions: int = 0,
    eligible_skus: Optional[list[str]] = None,
    earnings_count: int = 0,
    claimed_at: Optional[datetime] = None,
    earned_at: Optional[datetime] = None,
    pending_review: Optional[PendingReviewSummary] = None,
    recent_denial: Optional[RecentDenialSummary] = None,
) -> BrandCashbackDealResponse:
    return BrandCashbackDealResponse(
        id=campaign.id,
        brand_name=campaign.brand_name,
        product_name=campaign.product_name,
        description=campaign.description,
        cashback_amount=campaign.cashback_amount_cents / 100,
        image_url=image_url_for_key(campaign.image_s3_key),
        image_thumb_url=image_url_for_key(campaign.image_thumb_s3_key),
        valid_from=campaign.valid_from,
        valid_until=campaign.valid_until,
        eligible_stores=campaign.eligible_stores or [],
        requires_store=campaign.requires_store,
        user_status=user_status,
        earned_at=earned_at,
        terms=campaign.terms,
        how_it_works=campaign.how_it_works or [],
        max_redemptions_per_user=campaign.max_redemptions_per_user,
        total_redemption_cap=campaign.total_redemption_cap,
        category=campaign.category,
        featured=campaign.featured,
        current_redemptions=current_redemptions,
        eligible_skus=eligible_skus or [],
        earnings_count=earnings_count,
        claimed_at=claimed_at,
        pending_review=pending_review,
        recent_denial=recent_denial,
    )


def _is_campaign_full(campaign: BrandCashbackCampaign, earnings_for_campaign: int) -> bool:
    """Brand-level cap exhausted across all users."""
    return (
        campaign.total_redemption_cap is not None
        and earnings_for_campaign >= campaign.total_redemption_cap
    )


def _resolve_user_status(
    has_claim: bool,
    earnings_count: int,
    max_redemptions_per_user: int,
) -> str:
    if earnings_count >= max_redemptions_per_user:
        return "earned"
    if has_claim:
        return "claimed"
    return "available"


# Errors returned by approve_pending_match.
APPROVE_NOT_FOUND = "not_found"
APPROVE_ALREADY_REVIEWED = "already_reviewed"
APPROVE_CAMPAIGN_FULL = "campaign_cap_reached_during_review"
APPROVE_USER_LIMIT = "user_limit_reached_during_review"
APPROVE_CAMPAIGN_INACTIVE = "campaign_deactivated"
APPROVE_CAMPAIGN_EXPIRED = "campaign_expired"
APPROVE_RECEIPT_OUTSIDE = "receipt_outside_window"


class BrandCashbackService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = BrandCashbackRepository(db)

    # ------------------------------------------------------------------
    # User-facing
    # ------------------------------------------------------------------

    async def get_deals_for_user(self, user_id: str) -> list[BrandCashbackDealResponse]:
        """Active, not-expired, not-cap-exhausted campaigns annotated with the user's status.

        Excludes:
          - campaigns the user has already maxed out (status would be "earned")
          - campaigns whose total cap is exhausted
        Both vanish from the deals list — earned ones still appear in /my-claims for history.
        """
        campaigns = await self.repo.get_active_campaigns()
        claims = await self.repo.get_user_claims_by_campaign(user_id)
        earnings = await self.repo.get_user_earnings_by_campaign(user_id)
        pendings_by_campaign = self._index_pendings(
            await self.repo.get_pending_matches_for_user(user_id, status="pending")
        )
        denials_by_campaign = self._index_pendings(
            await self.repo.get_recent_denials_for_user(
                user_id, datetime.now(timezone.utc) - DENIAL_BANNER_TTL
            )
        )

        result = []
        for campaign in campaigns:
            user_earnings = earnings.get(campaign.id, [])
            earnings_count = len(user_earnings)
            has_claim = campaign.id in claims

            campaign_earnings = await self.repo.count_earnings_for_campaign(campaign.id)
            if _is_campaign_full(campaign, campaign_earnings):
                continue

            user_status = _resolve_user_status(
                has_claim, earnings_count, campaign.max_redemptions_per_user
            )
            if user_status == "earned":
                continue

            eligible_skus = await self.repo.get_distinct_exact_line_items(campaign.id)
            claim = claims.get(campaign.id)
            pending = pendings_by_campaign.get(campaign.id)
            denial = denials_by_campaign.get(campaign.id)

            result.append(
                campaign_to_deal_response(
                    campaign,
                    user_status,
                    current_redemptions=campaign_earnings,
                    eligible_skus=eligible_skus,
                    earnings_count=earnings_count,
                    claimed_at=claim.claimed_at if claim else None,
                    earned_at=user_earnings[0].earned_at if user_earnings else None,
                    pending_review=_to_pending_summary(pending) if pending else None,
                    recent_denial=_to_denial_summary(denial) if denial else None,
                )
            )
        return result

    async def claim_deal(
        self, user_id: str, campaign_id: str
    ) -> tuple[Optional[BrandCashbackClaim], Optional[str]]:
        """Idempotent claim.

        Returns (claim, error). On success, error is None. On failure, claim is None
        and error is one of: "not_found", "expired", "user_limit_reached", "campaign_full".
        """
        campaign = await self.repo.get_campaign_by_id(campaign_id)
        if not campaign or not campaign.is_active:
            return None, "not_found"

        now = datetime.now(timezone.utc)
        if campaign.valid_until <= now:
            return None, "expired"

        # Per-user cap (in earnings, not claims — claims are unique per pair).
        earnings_count = await self.repo.count_user_earnings_for_campaign(
            user_id, campaign_id
        )
        if earnings_count >= campaign.max_redemptions_per_user:
            return None, "user_limit_reached"

        # Total redemption cap.
        if campaign.total_redemption_cap is not None:
            campaign_earnings = await self.repo.count_earnings_for_campaign(campaign_id)
            if campaign_earnings >= campaign.total_redemption_cap:
                return None, "campaign_full"

        claim = await self.repo.upsert_claim(user_id, campaign_id)
        return claim, None

    async def unclaim_deal(self, user_id: str, campaign_id: str) -> bool:
        """Remove the user's claim. Earnings history is preserved."""
        return await self.repo.delete_claim(user_id, campaign_id)

    # ------------------------------------------------------------------
    # Receipt matching (called from receipt_background_worker)
    # ------------------------------------------------------------------

    async def check_receipt_for_brand_cashback(
        self,
        receipt_id: str,
        user_id: str,
        receipt_line_items: list[ReceiptLineItemForMatching],
        store_name: Optional[str],
        receipt_date: Optional[date],
    ) -> int:
        """For each campaign the user has claimed, attempt to match a receipt line item.

        Per-line-item routing:
          - Code-mode (line item has product_codes): match by code only — receipt
            line's `code` must be in line_item.product_codes. No text fallback,
            no fuzzy fallback. Used by Delhaize/Colruyt where receipts print a
            unique per-line code.
          - Text-mode (line item has empty product_codes):
              Pass 1 strict equality on text → instant earning.
              Pass 2 fuzzy fallback (>= QUEUE_THRESHOLD) → admin review queue.
            Used by AH/Carrefour/Aldi/Lidl which don't print per-line codes.

        Code-mode is checked first within a campaign; if any code matches, earn
        and skip the campaign's text-mode work. At most one earning is created
        per (claim, receipt) — the existing per-user / campaign cap logic stays.

        Returns the count of *instant* earnings created on this receipt; queued
        rows are not counted.

        Gate order (each gate fires its own skip log only when it is THE
        reason — earlier gates take priority):
          1. receipt_date is non-null (top-of-function early-out for whole receipt)
          2. claim list pre-filtered by repo: capped claims excluded entirely
             (see `get_active_claims_for_matching`)
          3. campaign is_active and not past valid_until
          4. campaign-wide earnings < total_redemption_cap (if set)
          5. receipt_date in [valid_from, valid_until], inclusive, day-precision
          6. if requires_store: store_name must be in eligible_stores
        """
        claims = await self.repo.get_active_claims_for_matching(user_id)
        if not claims:
            return 0

        # Hard reject: no usable proof-of-purchase date → nothing matches.
        # Today's prod data shows Gemini extracts dates reliably (0/58 nulls),
        # but a missing date is a fraud vector against tampered/unreadable
        # images, so we refuse to credit a wallet without one.
        if receipt_date is None:
            logger.info(
                f"Brand cashback: receipt {receipt_id} has no parseable date — "
                f"skipping all matching for user={user_id}"
            )
            return 0

        # Future-dated receipts are universally invalid (across all campaigns,
        # regardless of window). Phone-clock manipulation or tampered prints
        # land here. No earning, no review queue.
        today = date.today()
        if receipt_date > today:
            logger.info(
                f"Brand cashback: receipt {receipt_id} date={receipt_date} is in the future "
                f"(today={today}) — skipping all matching for user={user_id}"
            )
            return 0

        # Serialize concurrent receipt processings for the same user via a
        # transactional advisory lock. Two uploads racing on the per-user cap
        # would otherwise both observe `count < max` and both create earnings,
        # exceeding the cap by 1. Lock auto-releases at COMMIT (held until the
        # worker commits after this method returns). hashtext gives a stable
        # 32-bit slot from the user_id string.
        await self.db.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:user_id))"),
            {"user_id": user_id},
        )

        balance_repo = BrandCashbackBalanceRepository(self.db)
        now = datetime.now(timezone.utc)
        new_earnings = 0

        for claim in claims:
            campaign = claim.campaign
            if not campaign or not campaign.is_active:
                continue
            if campaign.valid_until <= now:
                continue

            # Per-user cap is enforced upstream by `get_active_claims_for_matching`
            # — capped claims are not in this list. No redundant COUNT here.

            # Campaign-wide cap (race-safe re-check). Different scope than the
            # per-user cap: it CAN flip during a single receipt's processing
            # if another user wins the race for the last slot. Row-lock the
            # campaign before the COUNT so two concurrent users don't both
            # observe `count < cap` and both earn.
            if campaign.total_redemption_cap is not None:
                await self.repo.lock_campaign_for_cap_check(campaign.id)
                campaign_earnings = await self.repo.count_earnings_for_campaign(
                    campaign.id
                )
                if campaign_earnings >= campaign.total_redemption_cap:
                    logger.info(
                        f"Brand cashback: campaign {campaign.id} full "
                        f"({campaign_earnings}/{campaign.total_redemption_cap}) — skipping match"
                    )
                    continue

            # Receipt must fall inside the campaign window (calendar-day,
            # inclusive on both ends). Backdated receipts (purchased before
            # the campaign existed) and forward-dated receipts past the end
            # are categorically disqualified — silent skip, no review queue
            # entry, since there's nothing for an admin to approve.
            if not (campaign.valid_from.date() <= receipt_date <= campaign.valid_until.date()):
                logger.info(
                    f"Brand cashback: receipt {receipt_id} date={receipt_date} is outside "
                    f"campaign {campaign.id} window "
                    f"[{campaign.valid_from.date()}..{campaign.valid_until.date()}] — skipping"
                )
                continue

            # Store eligibility.
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
                line_items = await self.repo.get_line_items_for_campaign(campaign.id)

            if not line_items:
                logger.debug(
                    f"Brand cashback: no line items configured for campaign {campaign.id} "
                    f"at store '{store_name}' — skipping"
                )
                continue

            # ---- Layered per-line-item matching ----
            # Tier 1: any receipt code hits a line-item product_code → instant earning.
            # Tier 2: receipt text exactly matches exact_line_item or alt → instant earning;
            #         if the receipt brought codes the line item doesn't know yet, auto-append
            #         them so future scans of the same (rotated) SKU hit Tier 1.
            # Tier 3: receipt text fuzzy-matches (>= QUEUE_THRESHOLD) → admin review queue.
            # First hit wins. Codes still required for Colruyt/Delhaize at admin time, but
            # text now serves as a fallback when SKUs rotate (new EANs, same description).
            matched_line_item_id: Optional[str] = None
            match_tier: Optional[str] = None
            matched_receipt_codes: list[str] = []

            # Tier 1 — code match
            code_index: dict[str, str] = {}
            for li in line_items:
                for code in (li.product_codes or []):
                    code_index[code] = li.id
            if code_index:
                for receipt_item in receipt_line_items:
                    for code in receipt_item.codes:
                        if code in code_index:
                            matched_line_item_id = code_index[code]
                            match_tier = "code"
                            break
                    if matched_line_item_id:
                        break

            # Tier 2 — text exact (only if no code match yet)
            if not matched_line_item_id:
                known_strings: list[tuple[str, str]] = []
                for li in line_items:
                    known_strings.append((li.id, li.exact_line_item))
                    for alt in (li.alt_line_items or []):
                        known_strings.append((li.id, alt))
                for receipt_item in receipt_line_items:
                    for li_id, known in known_strings:
                        if _is_line_item_match(receipt_item.text, known):
                            matched_line_item_id = li_id
                            match_tier = "text_exact"
                            matched_receipt_codes = list(receipt_item.codes)
                            break
                    if matched_line_item_id:
                        break

            # Earning + auto-extend for tier 2
            if matched_line_item_id:
                await self.repo.create_earning(
                    user_id=user_id,
                    campaign_id=campaign.id,
                    receipt_id=receipt_id,
                    matched_line_item_id=matched_line_item_id,
                    cashback_earned_cents=campaign.cashback_amount_cents,
                )
                await balance_repo.credit(user_id, campaign.cashback_amount_cents)
                new_earnings += 1
                proposed_codes = 0
                if match_tier == "text_exact" and matched_receipt_codes:
                    # Tier 2 (text exact) gives the user their earning, but
                    # the receipt's unknown codes go to the admin-review queue
                    # instead of being auto-appended to product_codes — a
                    # single fluke text match shouldn't globally pollute the
                    # allow-list. Approved proposals call add_product_codes
                    # later from the admin endpoint.
                    proposed_codes = await self.repo.propose_product_codes(
                        line_item_id=matched_line_item_id,
                        codes=matched_receipt_codes,
                        source_user_id=user_id,
                        source_receipt_id=receipt_id,
                    )
                logger.info(
                    f"Brand cashback earned: user={user_id} campaign={campaign.id} "
                    f"store='{store_name}' amount_cents={campaign.cashback_amount_cents} "
                    f"tier={match_tier} proposed_codes={proposed_codes}"
                )
                continue

            # Pass 2: fuzzy fallback for the review queue
            best_score = 0.0
            best_li_id: Optional[str] = None
            best_receipt_str: Optional[str] = None
            for receipt_item in receipt_line_items:
                for li_id, known in known_strings:
                    score = _fuzzy_score(receipt_item.text, known)
                    if score > best_score:
                        best_score = score
                        best_li_id = li_id
                        best_receipt_str = receipt_item.text

            if best_score >= QUEUE_THRESHOLD and best_li_id and best_receipt_str:
                created = await self.repo.create_pending_match(
                    user_id=user_id,
                    campaign_id=campaign.id,
                    receipt_id=receipt_id,
                    candidate_string=best_receipt_str,
                    matched_line_item_id=best_li_id,
                    match_score=best_score,
                    store_name=store_name,
                )
                if created:
                    logger.info(
                        f"Brand cashback queued for review: user={user_id} "
                        f"campaign={campaign.id} score={best_score:.3f} "
                        f"candidate='{best_receipt_str}'"
                    )

        return new_earnings

    # ------------------------------------------------------------------
    # Admin review actions
    # ------------------------------------------------------------------

    async def approve_pending_match(
        self,
        pending_id: str,
        reviewer_id: str,
        add_to_alts: bool,
    ) -> tuple[Optional[BrandCashbackEarning], Optional[str]]:
        """Approve a pending match → create earning + credit points.

        Returns (earning, error). On success, error is None.

        Auto-denies (and returns the corresponding error) if the campaign cap or
        per-user cap has been reached since the pending row was created.
        """
        pending = await self.repo.lock_pending_match(pending_id)
        if not pending:
            return None, APPROVE_NOT_FOUND
        if pending.status != "pending":
            return None, APPROVE_ALREADY_REVIEWED

        campaign = pending.campaign
        balance_repo = BrandCashbackBalanceRepository(self.db)
        now = datetime.now(timezone.utc)

        # Per-user advisory lock — admin double-clicking, or admin approving
        # while the user simultaneously uploads a new receipt, must serialize
        # so the per-user cap can't be raced.
        await self.db.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:user_id))"),
            {"user_id": pending.user_id},
        )

        async def _auto_deny(reason: str) -> tuple[None, str]:
            """Mark the pending row denied AND commit before returning, so the
            FastAPI HTTPException downstream doesn't roll back the auto-deny.
            Without this commit, get_db's `except: rollback` reverts the deny
            because raising HTTPException counts as an exception in that scope.
            """
            await self.repo.mark_pending_denied(pending_id, reviewer_id, reason)
            await self.db.commit()
            return None, reason

        # Re-check campaign validity — the pending row may have aged. Admin
        # could have deactivated, expired, or shifted the window since queue.
        if not campaign.is_active:
            return await _auto_deny(APPROVE_CAMPAIGN_INACTIVE)
        if campaign.valid_until <= now:
            return await _auto_deny(APPROVE_CAMPAIGN_EXPIRED)
        if pending.receipt and pending.receipt.receipt_date:
            rd = pending.receipt.receipt_date
            if not (campaign.valid_from.date() <= rd <= campaign.valid_until.date()):
                return await _auto_deny(APPROVE_RECEIPT_OUTSIDE)

        # Re-check caps; state may have shifted between queue and review.
        user_earnings = await self.repo.count_user_earnings_for_campaign(
            pending.user_id, pending.campaign_id
        )
        if user_earnings >= campaign.max_redemptions_per_user:
            return await _auto_deny(APPROVE_USER_LIMIT)

        if campaign.total_redemption_cap is not None:
            await self.repo.lock_campaign_for_cap_check(campaign.id)
            campaign_earnings = await self.repo.count_earnings_for_campaign(
                pending.campaign_id
            )
            if campaign_earnings >= campaign.total_redemption_cap:
                return await _auto_deny(APPROVE_CAMPAIGN_FULL)

        if not pending.matched_line_item_id:
            # Should not happen — pending rows are created with a matched line item —
            # but guard against orphans (e.g. line item deleted after queueing).
            return await _auto_deny("matched_line_item_missing")

        earning = await self.repo.create_earning(
            user_id=pending.user_id,
            campaign_id=pending.campaign_id,
            receipt_id=pending.receipt_id,
            matched_line_item_id=pending.matched_line_item_id,
            cashback_earned_cents=campaign.cashback_amount_cents,
        )

        await balance_repo.credit(pending.user_id, campaign.cashback_amount_cents)

        if add_to_alts:
            await self.repo.add_alt_line_item(
                pending.matched_line_item_id, pending.candidate_string
            )

        await self.repo.mark_pending_approved(pending_id, reviewer_id, earning.id)

        logger.info(
            f"Brand cashback review approved: pending={pending_id} "
            f"user={pending.user_id} campaign={pending.campaign_id} "
            f"add_to_alts={add_to_alts}"
        )
        return earning, None

    async def deny_pending_match(
        self, pending_id: str, reviewer_id: str, reason: str
    ) -> Optional[str]:
        """Deny a pending match. Returns an error string or None on success."""
        pending = await self.repo.lock_pending_match(pending_id)
        if not pending:
            return APPROVE_NOT_FOUND
        if pending.status != "pending":
            return APPROVE_ALREADY_REVIEWED
        await self.repo.mark_pending_denied(pending_id, reviewer_id, reason)
        logger.info(
            f"Brand cashback review denied: pending={pending_id} "
            f"user={pending.user_id} campaign={pending.campaign_id} reason='{reason}'"
        )
        return None

    # ------------------------------------------------------------------
    # Code-extension proposals (admin-reviewed Tier 2 → product_codes path)
    # ------------------------------------------------------------------

    async def approve_code_proposal(
        self, proposal_id: str, reviewer_id: str
    ) -> Optional[str]:
        """Approve a queued code proposal: append the code to the line item's
        product_codes and mark the proposal approved. Idempotent against
        already-reviewed rows (returns APPROVE_ALREADY_REVIEWED).
        """
        proposal = await self.repo.get_code_proposal(proposal_id)
        if proposal is None:
            return APPROVE_NOT_FOUND
        if proposal.status != "pending":
            return APPROVE_ALREADY_REVIEWED
        await self.repo.add_product_codes(proposal.line_item_id, [proposal.code])
        await self.repo.mark_code_proposal_approved(proposal_id, reviewer_id)
        logger.info(
            f"Brand cashback code proposal approved: proposal={proposal_id} "
            f"line_item={proposal.line_item_id} code={proposal.code} "
            f"reviewer={reviewer_id}"
        )
        return None

    async def reject_code_proposal(
        self, proposal_id: str, reviewer_id: str, reason: str
    ) -> Optional[str]:
        """Reject a queued code proposal. Code is NOT added; reason is stored
        for audit. Idempotent against already-reviewed rows."""
        proposal = await self.repo.get_code_proposal(proposal_id)
        if proposal is None:
            return APPROVE_NOT_FOUND
        if proposal.status != "pending":
            return APPROVE_ALREADY_REVIEWED
        await self.repo.mark_code_proposal_rejected(proposal_id, reviewer_id, reason)
        logger.info(
            f"Brand cashback code proposal rejected: proposal={proposal_id} "
            f"line_item={proposal.line_item_id} code={proposal.code} "
            f"reason='{reason}' reviewer={reviewer_id}"
        )
        return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _index_pendings(
        rows: list[BrandCashbackPendingMatch],
    ) -> dict[str, BrandCashbackPendingMatch]:
        """Most-recent row per campaign (rows are pre-sorted DESC by created/reviewed_at)."""
        out: dict[str, BrandCashbackPendingMatch] = {}
        for r in rows:
            if r.campaign_id not in out:
                out[r.campaign_id] = r
        return out
