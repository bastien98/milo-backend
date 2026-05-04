"""Gating tests for `BrandCashbackService.check_receipt_for_brand_cashback`.

Focus: the validity gauntlet (receipt date present + within campaign window).
Tier matching (code/text/fuzzy) is exercised by production e2e until we have
a DB fixture rig — stubbing the repo here would bind the test to internal
ordering rather than verify behaviour.

These tests stub `get_user_claims_with_campaigns` to return hand-built
campaigns and assert that the rejected paths short-circuit *before* any
mutation methods are called (`create_earning`, `create_pending_match`,
`balance_repo.credit`). That's enough to lock in the gating contract.
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime, date, timedelta, timezone
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.brand_cashback_service import (
    BrandCashbackService,
    ReceiptLineItemForMatching,
)


def _run(coro):
    """Run a single coroutine synchronously — avoids needing pytest-asyncio."""
    return asyncio.run(coro)


@dataclass
class _StubCampaign:
    id: str
    is_active: bool
    valid_from: datetime
    valid_until: datetime
    max_redemptions_per_user: int = 1
    total_redemption_cap: Optional[int] = None
    requires_store: bool = False
    eligible_stores: Optional[list] = None
    cashback_amount_cents: int = 100


@dataclass
class _StubClaim:
    campaign: _StubCampaign


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _campaign(
    *,
    valid_from_offset_days: int = -1,
    valid_until_offset_days: int = 30,
    is_active: bool = True,
) -> _StubCampaign:
    """Build a stub campaign whose window is `valid_from_offset_days` to
    `valid_until_offset_days` relative to today."""
    n = _now_utc()
    return _StubCampaign(
        id=f"camp-{valid_from_offset_days}-{valid_until_offset_days}",
        is_active=is_active,
        valid_from=n + timedelta(days=valid_from_offset_days),
        valid_until=n + timedelta(days=valid_until_offset_days),
    )


def _service_with_claims(claims: list[_StubClaim]) -> tuple[BrandCashbackService, MagicMock]:
    """Wire a service with a fully-mocked repo whose only working method is
    `get_user_claims_with_campaigns`. All mutation methods are AsyncMocks
    that we assert are never called when the gating logic short-circuits."""
    db = MagicMock()
    # The matcher now executes raw SQL for the per-user advisory lock and the
    # campaign-cap row lock — make `db.execute` awaitable so those don't blow
    # up under MagicMock's default sync behaviour.
    db.execute = AsyncMock()
    svc = BrandCashbackService(db)

    repo = MagicMock()
    # Matcher now uses the cap-pre-filtered method. Tests pass the claim list
    # they want the matcher to see; capped claims are simulated by NOT
    # including them in `claims`.
    repo.get_active_claims_for_matching = AsyncMock(return_value=claims)
    # Legacy method still exists (read-side surfaces use it); keep stubbed
    # for any test that might check it isn't called by the matcher.
    repo.get_user_claims_with_campaigns = AsyncMock(return_value=claims)
    repo.count_user_earnings_for_campaign = AsyncMock(return_value=0)
    repo.count_earnings_for_campaign = AsyncMock(return_value=0)
    repo.get_line_items_for_campaign = AsyncMock(return_value=[])
    repo.get_line_items_for_campaign_store = AsyncMock(return_value=[])
    repo.create_earning = AsyncMock()
    repo.create_pending_match = AsyncMock()
    repo.add_product_codes = AsyncMock()
    svc.repo = repo
    return svc, repo


def test_null_receipt_date_short_circuits():
    """No date → return 0 immediately, no per-campaign work."""
    svc, repo = _service_with_claims([_StubClaim(_campaign())])

    with patch(
        "app.services.brand_cashback_service.BrandCashbackBalanceRepository"
    ) as balance_cls:
        balance_cls.return_value.credit = AsyncMock()

        n = _run(svc.check_receipt_for_brand_cashback(
            receipt_id="r1",
            user_id="u1",
            receipt_line_items=[ReceiptLineItemForMatching(text="X", codes=())],
            store_name="Carrefour Express",
            receipt_date=None,
        ))

    assert n == 0
    repo.create_earning.assert_not_awaited()
    repo.create_pending_match.assert_not_awaited()


def test_receipt_before_campaign_window_skips_that_campaign():
    """Receipt dated before valid_from → that campaign skipped (no earning,
    no pending). Other in-window campaigns must still be evaluated."""
    early = _campaign(valid_from_offset_days=-1, valid_until_offset_days=30)
    older_only = _StubClaim(early)
    svc, repo = _service_with_claims([older_only])

    # Receipt from 10 days BEFORE valid_from.
    backdate = early.valid_from.date() - timedelta(days=10)

    with patch(
        "app.services.brand_cashback_service.BrandCashbackBalanceRepository"
    ) as balance_cls:
        balance_cls.return_value.credit = AsyncMock()

        n = _run(svc.check_receipt_for_brand_cashback(
            receipt_id="r1",
            user_id="u1",
            receipt_line_items=[ReceiptLineItemForMatching(text="X", codes=())],
            store_name=None,
            receipt_date=backdate,
        ))

    assert n == 0
    repo.create_earning.assert_not_awaited()
    repo.create_pending_match.assert_not_awaited()
    # Must have early-skipped before fetching line items for this campaign.
    repo.get_line_items_for_campaign.assert_not_awaited()


def test_receipt_after_campaign_window_skipped():
    """Receipt past valid_until — also caught by the existing
    `valid_until <= now` check, but the new check makes the intent explicit
    and works even if `now` shifts due to clock drift between processing
    nodes."""
    # Put valid_until 1 day in the past so the existing now-check fires too.
    expired = _campaign(valid_from_offset_days=-30, valid_until_offset_days=-1)
    svc, repo = _service_with_claims([_StubClaim(expired)])

    receipt_date = date.today()

    with patch(
        "app.services.brand_cashback_service.BrandCashbackBalanceRepository"
    ) as balance_cls:
        balance_cls.return_value.credit = AsyncMock()

        n = _run(svc.check_receipt_for_brand_cashback(
            receipt_id="r1",
            user_id="u1",
            receipt_line_items=[ReceiptLineItemForMatching(text="X", codes=())],
            store_name=None,
            receipt_date=receipt_date,
        ))

    assert n == 0
    repo.create_earning.assert_not_awaited()


def test_receipt_on_valid_from_boundary_passes_window_gate():
    """Boundary inclusivity — receipt dated exactly on valid_from is in-window."""
    c = _campaign(valid_from_offset_days=0, valid_until_offset_days=30)
    svc, repo = _service_with_claims([_StubClaim(c)])

    boundary = c.valid_from.date()

    with patch(
        "app.services.brand_cashback_service.BrandCashbackBalanceRepository"
    ) as balance_cls:
        balance_cls.return_value.credit = AsyncMock()

        n = _run(svc.check_receipt_for_brand_cashback(
            receipt_id="r1",
            user_id="u1",
            receipt_line_items=[ReceiptLineItemForMatching(text="X", codes=())],
            store_name=None,
            receipt_date=boundary,
        ))

    # Window gate passed → matcher proceeded to line-item lookup. No matches
    # because we returned an empty list — that's expected; the assertion
    # is that we got *past* the gate.
    assert n == 0
    repo.get_line_items_for_campaign.assert_awaited_once()


def test_receipt_on_valid_until_boundary_passes_window_gate():
    """Boundary inclusivity — receipt dated exactly on valid_until is in-window.

    Tricky to set up: valid_until's datetime must be > now (so the existing
    `valid_until <= now` check passes) AND its `.date()` must equal `date.today()`
    in the matcher's local timezone (so the future-date guard doesn't reject).
    Solution: anchor valid_until to today's end-of-day in the local zone."""
    today = date.today()
    eod_local = datetime.combine(today, datetime.max.time(), tzinfo=timezone.utc)
    c = _StubCampaign(
        id="camp-boundary",
        is_active=True,
        valid_from=_now_utc() - timedelta(days=7),
        valid_until=eod_local,
    )
    svc, repo = _service_with_claims([_StubClaim(c)])

    boundary = today

    with patch(
        "app.services.brand_cashback_service.BrandCashbackBalanceRepository"
    ) as balance_cls:
        balance_cls.return_value.credit = AsyncMock()

        n = _run(svc.check_receipt_for_brand_cashback(
            receipt_id="r1",
            user_id="u1",
            receipt_line_items=[ReceiptLineItemForMatching(text="X", codes=())],
            store_name=None,
            receipt_date=boundary,
        ))

    assert n == 0
    repo.get_line_items_for_campaign.assert_awaited_once()


def test_one_campaign_in_window_other_out_skips_only_the_out_one():
    """Mixed claims: one campaign in-window, one before. The in-window one
    must still be evaluated; the out-of-window one must be skipped without
    fetching its line items."""
    in_window = _campaign(valid_from_offset_days=-1, valid_until_offset_days=30)
    out_window = _campaign(valid_from_offset_days=10, valid_until_offset_days=40)
    svc, repo = _service_with_claims([_StubClaim(in_window), _StubClaim(out_window)])

    # Today — in window for the first, before window for the second.
    today = date.today()

    with patch(
        "app.services.brand_cashback_service.BrandCashbackBalanceRepository"
    ) as balance_cls:
        balance_cls.return_value.credit = AsyncMock()

        n = _run(svc.check_receipt_for_brand_cashback(
            receipt_id="r1",
            user_id="u1",
            receipt_line_items=[ReceiptLineItemForMatching(text="X", codes=())],
            store_name=None,
            receipt_date=today,
        ))

    assert n == 0
    # Line-item lookup ran exactly once — for the in-window campaign only.
    assert repo.get_line_items_for_campaign.await_count == 1


# ---------------------------------------------------------------------------
# Cap-pre-filter tests: matcher reads only non-capped claims via repo
# ---------------------------------------------------------------------------

def test_capped_claim_never_reaches_matcher():
    """When the user is at cap, the repo returns [] for that user. The matcher
    short-circuits with no per-claim work and no log noise."""
    # Repo returns [] — emulating the cap-pre-filter excluding all claims.
    svc, repo = _service_with_claims([])

    with patch(
        "app.services.brand_cashback_service.BrandCashbackBalanceRepository"
    ) as balance_cls:
        balance_cls.return_value.credit = AsyncMock()

        n = _run(svc.check_receipt_for_brand_cashback(
            receipt_id="r1",
            user_id="u1",
            receipt_line_items=[ReceiptLineItemForMatching(text="X", codes=())],
            store_name=None,
            receipt_date=date.today(),
        ))

    assert n == 0
    # Critical: the matcher must consult the new pre-filtered method, NOT the
    # legacy unfiltered one.
    repo.get_active_claims_for_matching.assert_awaited_once_with("u1")
    repo.get_user_claims_with_campaigns.assert_not_awaited()
    repo.count_user_earnings_for_campaign.assert_not_awaited()
    repo.get_line_items_for_campaign.assert_not_awaited()
    repo.create_earning.assert_not_awaited()
    repo.create_pending_match.assert_not_awaited()


def test_non_capped_claim_runs_through_matcher_normally():
    """Claim returned by the pre-filter (non-capped) → date gate + line item
    lookup execute normally."""
    c = _campaign(valid_from_offset_days=-1, valid_until_offset_days=30)
    svc, repo = _service_with_claims([_StubClaim(c)])

    with patch(
        "app.services.brand_cashback_service.BrandCashbackBalanceRepository"
    ) as balance_cls:
        balance_cls.return_value.credit = AsyncMock()

        n = _run(svc.check_receipt_for_brand_cashback(
            receipt_id="r1",
            user_id="u1",
            receipt_line_items=[ReceiptLineItemForMatching(text="X", codes=())],
            store_name=None,
            receipt_date=date.today(),
        ))

    # Date gate passed, line items fetched (empty list returned by stub → no match).
    assert n == 0
    repo.get_active_claims_for_matching.assert_awaited_once()
    repo.get_line_items_for_campaign.assert_awaited_once()
    # No redundant cap COUNT — pre-filter handled it.
    repo.count_user_earnings_for_campaign.assert_not_awaited()


def test_mixed_only_non_capped_passed_to_matcher():
    """Repo emulates pre-filter by passing only the non-capped claim. Matcher
    iterates ONE campaign, the in-window one. The capped one isn't even seen."""
    in_window = _campaign(valid_from_offset_days=-1, valid_until_offset_days=30)
    # Note: we don't include the capped claim in the list — that's the contract
    # of the pre-filtered method.
    svc, repo = _service_with_claims([_StubClaim(in_window)])

    with patch(
        "app.services.brand_cashback_service.BrandCashbackBalanceRepository"
    ) as balance_cls:
        balance_cls.return_value.credit = AsyncMock()

        n = _run(svc.check_receipt_for_brand_cashback(
            receipt_id="r1",
            user_id="u1",
            receipt_line_items=[ReceiptLineItemForMatching(text="X", codes=())],
            store_name=None,
            receipt_date=date.today(),
        ))

    assert n == 0
    # Exactly one campaign considered (the non-capped, in-window one).
    repo.get_line_items_for_campaign.assert_awaited_once()


# ---------------------------------------------------------------------------
# Fix #6: future-dated receipt rejected at top of matcher
# ---------------------------------------------------------------------------

def test_future_dated_receipt_rejected_universally():
    """Receipt date > today → return 0, no per-claim work, no advisory lock."""
    in_window = _campaign(valid_from_offset_days=-1, valid_until_offset_days=30)
    svc, repo = _service_with_claims([_StubClaim(in_window)])

    tomorrow = date.today() + timedelta(days=1)

    with patch(
        "app.services.brand_cashback_service.BrandCashbackBalanceRepository"
    ) as balance_cls:
        balance_cls.return_value.credit = AsyncMock()

        n = _run(svc.check_receipt_for_brand_cashback(
            receipt_id="r1",
            user_id="u1",
            receipt_line_items=[ReceiptLineItemForMatching(text="X", codes=())],
            store_name=None,
            receipt_date=tomorrow,
        ))

    assert n == 0
    # No per-claim work — guard fires at the top.
    repo.get_line_items_for_campaign.assert_not_awaited()
    repo.create_earning.assert_not_awaited()
    repo.create_pending_match.assert_not_awaited()


# ---------------------------------------------------------------------------
# Fix #7: Tier 2 hit queues code proposals (NOT direct extend)
# ---------------------------------------------------------------------------

def test_tier2_hit_calls_propose_codes_not_add():
    """When Tier 2 (text exact) fires with unknown receipt codes, the matcher
    calls `propose_product_codes` (admin-review queue), NOT the legacy direct
    `add_product_codes`. The earning still fires."""
    c = _campaign(valid_from_offset_days=-1, valid_until_offset_days=30)
    svc, repo = _service_with_claims([_StubClaim(c)])

    # Stub a single line item with empty product_codes (text-mode) and
    # exact text matching the receipt input below.
    line_item = MagicMock()
    line_item.id = "li-1"
    line_item.exact_line_item = "MAGIC SODA 50CL"
    line_item.alt_line_items = []
    line_item.product_codes = []
    repo.get_line_items_for_campaign = AsyncMock(return_value=[line_item])
    repo.create_earning = AsyncMock(return_value=MagicMock(id="earn-1"))
    repo.propose_product_codes = AsyncMock(return_value=2)

    receipt_codes = ("12345", "67890")

    with patch(
        "app.services.brand_cashback_service.BrandCashbackBalanceRepository"
    ) as balance_cls:
        balance_cls.return_value.credit = AsyncMock()

        n = _run(svc.check_receipt_for_brand_cashback(
            receipt_id="rc-1",
            user_id="u1",
            receipt_line_items=[
                ReceiptLineItemForMatching(text="MAGIC SODA 50CL", codes=receipt_codes)
            ],
            store_name=None,
            receipt_date=date.today(),
        ))

    assert n == 1
    repo.create_earning.assert_awaited_once()
    # Critical: proposal queue, not direct extend.
    repo.propose_product_codes.assert_awaited_once_with(
        line_item_id="li-1",
        codes=list(receipt_codes),
        source_user_id="u1",
        source_receipt_id="rc-1",
    )
    repo.add_product_codes.assert_not_awaited()


# ---------------------------------------------------------------------------
# Fix #1: approve_pending_match re-checks campaign validity
# ---------------------------------------------------------------------------

def _build_pending(campaign, *, status="pending", receipt_date_offset=-3):
    """Build a stub pending-match row that approve_pending_match expects."""
    pending = MagicMock()
    pending.id = "pending-1"
    pending.user_id = "u1"
    pending.campaign_id = campaign.id
    pending.campaign = campaign
    pending.status = status
    pending.matched_line_item_id = "li-1"
    pending.candidate_string = "MAGIC SODA"
    pending.receipt = MagicMock()
    pending.receipt.receipt_date = date.today() + timedelta(days=receipt_date_offset)
    return pending


def test_approve_denies_when_campaign_inactive():
    """A pending row whose campaign got deactivated since queueing → approve
    auto-denies with `campaign_deactivated`, no earning created."""
    from app.services.brand_cashback_service import APPROVE_CAMPAIGN_INACTIVE

    inactive_campaign = _campaign(
        valid_from_offset_days=-7, valid_until_offset_days=30, is_active=False
    )
    svc, repo = _service_with_claims([])

    pending = _build_pending(inactive_campaign)
    repo.lock_pending_match = AsyncMock(return_value=pending)
    repo.mark_pending_denied = AsyncMock()
    repo.create_earning = AsyncMock()

    with patch(
        "app.services.brand_cashback_service.BrandCashbackBalanceRepository"
    ) as balance_cls:
        balance_cls.return_value.credit = AsyncMock()

        earning, error = _run(svc.approve_pending_match(
            pending_id="pending-1", reviewer_id="admin-1", add_to_alts=True,
        ))

    assert error == APPROVE_CAMPAIGN_INACTIVE
    assert earning is None
    repo.create_earning.assert_not_awaited()
    repo.mark_pending_denied.assert_awaited_once_with(
        "pending-1", "admin-1", APPROVE_CAMPAIGN_INACTIVE
    )


def test_approve_denies_when_campaign_expired():
    """Campaign valid_until in the past → approve auto-denies with `campaign_expired`."""
    from app.services.brand_cashback_service import APPROVE_CAMPAIGN_EXPIRED

    expired_campaign = _campaign(valid_from_offset_days=-30, valid_until_offset_days=-1)
    svc, repo = _service_with_claims([])

    pending = _build_pending(expired_campaign)
    repo.lock_pending_match = AsyncMock(return_value=pending)
    repo.mark_pending_denied = AsyncMock()
    repo.create_earning = AsyncMock()

    with patch(
        "app.services.brand_cashback_service.BrandCashbackBalanceRepository"
    ) as balance_cls:
        balance_cls.return_value.credit = AsyncMock()

        earning, error = _run(svc.approve_pending_match(
            pending_id="pending-1", reviewer_id="admin-1", add_to_alts=True,
        ))

    assert error == APPROVE_CAMPAIGN_EXPIRED
    assert earning is None
    repo.create_earning.assert_not_awaited()


def test_approve_denies_when_receipt_outside_window():
    """Receipt date predates valid_from (admin shifted window after queueing)
    → approve auto-denies with `receipt_outside_window`."""
    from app.services.brand_cashback_service import APPROVE_RECEIPT_OUTSIDE

    # Campaign window starts a day ago, receipt is 5 days ago — outside.
    c = _campaign(valid_from_offset_days=-1, valid_until_offset_days=30)
    svc, repo = _service_with_claims([])

    pending = _build_pending(c, receipt_date_offset=-5)
    repo.lock_pending_match = AsyncMock(return_value=pending)
    repo.mark_pending_denied = AsyncMock()
    repo.create_earning = AsyncMock()

    with patch(
        "app.services.brand_cashback_service.BrandCashbackBalanceRepository"
    ) as balance_cls:
        balance_cls.return_value.credit = AsyncMock()

        earning, error = _run(svc.approve_pending_match(
            pending_id="pending-1", reviewer_id="admin-1", add_to_alts=True,
        ))

    assert error == APPROVE_RECEIPT_OUTSIDE
    assert earning is None
    repo.create_earning.assert_not_awaited()
