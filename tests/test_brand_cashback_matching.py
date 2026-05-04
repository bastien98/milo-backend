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
    svc = BrandCashbackService(db)

    repo = MagicMock()
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
    """Boundary inclusivity — receipt dated exactly on valid_until is in-window."""
    c = _campaign(valid_from_offset_days=-30, valid_until_offset_days=30)
    svc, repo = _service_with_claims([_StubClaim(c)])

    boundary = c.valid_until.date()

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
