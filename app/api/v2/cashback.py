from math import ceil

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, or_, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_current_db_user
from app.models.referral import Referral
from app.models.enums import CashbackStatus, SpinType
from app.models.user import User
from app.services.cashback_service import CashbackService
from app.services.kickstart_service import get_kickstart_progress
from app.services.tier_service import get_user_tier
from app.services.referral_service import REWARD_EUROS
from app.schemas.cashback import (
    CashbackBalanceResponse,
    CashbackSummaryResponse,
    CashbackHistoryResponse,
    CashbackTransactionResponse,
    CashbackClaimResponse,
    KickstartProgressResponse,
    POINTS_PER_EURO,
)

router = APIRouter()

REFERRAL_REWARD_POINTS = round(REWARD_EUROS * POINTS_PER_EURO)


def _build_balance_response(balance, tier, kickstart_prog) -> CashbackBalanceResponse:
    euro_value = round(balance.points_balance / POINTS_PER_EURO, 2)
    return CashbackBalanceResponse(
        points_balance=balance.points_balance,
        total_points_earned=balance.total_points_earned,
        total_points_paid_out=balance.total_points_paid_out,
        standard_spins=balance.standard_spins,
        premium_spins=balance.premium_spins,
        tier_level=tier.value,
        kickstart_progress=KickstartProgressResponse(**kickstart_prog),
        euro_value=euro_value,
        can_withdraw=balance.points_balance >= 10000,
        is_gold_tier=(tier.value == "gold"),
        spins_available=balance.standard_spins + balance.premium_spins,
        current_balance=euro_value,
        total_earned=round(balance.total_points_earned / POINTS_PER_EURO, 2),
        total_paid_out=round(balance.total_points_paid_out / POINTS_PER_EURO, 2),
    )


@router.get("/balance", response_model=CashbackBalanceResponse)
async def get_balance(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
):
    """Get the user's current Milo Points wallet balance."""
    svc = CashbackService(db)
    balance = await svc.get_balance(current_user.id)
    tier = await get_user_tier(db, balance)
    kickstart_prog = get_kickstart_progress(balance)
    await db.commit()
    return _build_balance_response(balance, tier, kickstart_prog)


@router.get("/summary", response_model=CashbackSummaryResponse)
async def get_summary(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
):
    """Get cashback summary: balance, recent transactions, and stats."""
    svc = CashbackService(db)
    balance = await svc.get_balance(current_user.id)
    tier = await get_user_tier(db, balance)
    kickstart_prog = get_kickstart_progress(balance)

    transactions, total = await svc.get_transaction_history(
        current_user.id, page=1, page_size=10
    )

    recent = []
    for txn in transactions:
        if txn.status not in (CashbackStatus.CONFIRMED, CashbackStatus.PAID_OUT):
            continue
        receipt = txn.receipt
        recent.append(
            CashbackTransactionResponse(
                id=txn.id,
                receipt_id=txn.receipt_id,
                receipt_total=txn.receipt_total,
                points_total=txn.points_total,
                fixed_points=txn.fixed_points,
                grote_kar_points=txn.grote_kar_points,
                kickstart_bonus_points=txn.kickstart_bonus_points,
                spin_type=txn.spin_type.value if txn.spin_type else None,
                is_kickstart=txn.is_kickstart,
                is_streak_saver=txn.is_streak_saver,
                status=txn.status,
                created_at=txn.created_at,
                store_name=receipt.store_name if receipt else None,
                receipt_date=receipt.receipt_date if receipt else None,
                cashback_amount=round(txn.points_total / POINTS_PER_EURO, 2),
            )
        )

    # Claimed referral rewards
    referral_result = await db.execute(
        select(Referral).where(
            or_(
                and_(Referral.referrer_id == current_user.id, Referral.referrer_reward_claimed == True),
                and_(Referral.referee_id == current_user.id, Referral.referee_reward_claimed == True),
            )
        ).order_by(Referral.completed_at.desc())
    )
    for ref in referral_result.scalars().all():
        recent.append(
            CashbackTransactionResponse(
                id=f"referral-{ref.id}",
                receipt_id=f"referral-{ref.id}",
                receipt_total=0,
                points_total=REFERRAL_REWARD_POINTS,
                status=CashbackStatus.CONFIRMED,
                created_at=ref.completed_at or ref.created_at,
                store_name="Referral Bonus",
                cashback_amount=REWARD_EUROS,
                spins_awarded=0,
                is_referral_reward=True,
            )
        )

    # Claimed streak rewards
    from app.models.streak import StreakReward
    from app.models.enums import StreakRewardStatus
    streak_result = await db.execute(
        select(StreakReward).where(
            StreakReward.user_id == current_user.id,
            StreakReward.status == StreakRewardStatus.CLAIMED,
        ).order_by(StreakReward.claimed_at.desc()).limit(10)
    )
    for sr in streak_result.scalars().all():
        recent.append(
            CashbackTransactionResponse(
                id=f"streak-{sr.id}",
                receipt_id=f"streak-{sr.id}",
                receipt_total=0,
                points_total=sr.points_amount,
                status=CashbackStatus.CONFIRMED,
                created_at=sr.claimed_at or sr.created_at,
                store_name=f"Streak Week {sr.week_number} (Level {sr.streak_level})",
                spins_awarded=sr.spins_amount,
                is_streak_reward=True,
            )
        )

    recent.sort(key=lambda x: x.created_at, reverse=True)

    avg_points = round(balance.total_points_earned / total, 0) if total > 0 else 0.0
    balance_resp = _build_balance_response(balance, tier, kickstart_prog)
    await db.commit()

    return CashbackSummaryResponse(
        balance=balance_resp,
        recent_transactions=recent,
        avg_points_per_receipt=avg_points,
        total_receipts_with_rewards=total,
        tier_level=tier.value,
        avg_cashback_per_receipt=round(avg_points / POINTS_PER_EURO, 4),
        total_receipts_with_cashback=total,
        is_gold_tier=(tier.value == "gold"),
    )


@router.get("/history", response_model=CashbackHistoryResponse)
async def get_history(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
):
    svc = CashbackService(db)
    transactions, total = await svc.get_transaction_history(
        current_user.id, page=page, page_size=page_size
    )

    items = []
    for txn in transactions:
        receipt = txn.receipt
        items.append(
            CashbackTransactionResponse(
                id=txn.id,
                receipt_id=txn.receipt_id,
                receipt_total=txn.receipt_total,
                points_total=txn.points_total,
                fixed_points=txn.fixed_points,
                grote_kar_points=txn.grote_kar_points,
                kickstart_bonus_points=txn.kickstart_bonus_points,
                spin_type=txn.spin_type.value if txn.spin_type else None,
                is_kickstart=txn.is_kickstart,
                is_streak_saver=txn.is_streak_saver,
                status=txn.status,
                created_at=txn.created_at,
                store_name=receipt.store_name if receipt else None,
                receipt_date=receipt.receipt_date if receipt else None,
                cashback_amount=round(txn.points_total / POINTS_PER_EURO, 2),
            )
        )

    total_pages = ceil(total / page_size) if total > 0 else 1
    return CashbackHistoryResponse(
        transactions=items, total=total, page=page,
        page_size=page_size, total_pages=total_pages,
    )


@router.post("/claim/{receipt_id}", response_model=CashbackClaimResponse)
async def claim_cashback(
    receipt_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
):
    """Confirm a pending reward and credit it to the user's points wallet. Idempotent."""
    svc = CashbackService(db)
    txn = await svc.claim_cashback(current_user.id, receipt_id)
    if txn is None:
        raise HTTPException(status_code=404, detail="No transaction found for this receipt")

    balance = await svc.get_balance(current_user.id)
    await db.commit()

    euro_value = round(balance.points_balance / POINTS_PER_EURO, 2)
    return CashbackClaimResponse(
        receipt_id=receipt_id,
        points_total=txn.points_total,
        spin_type=txn.spin_type.value if txn.spin_type else None,
        new_points_balance=balance.points_balance,
        euro_value=euro_value,
        cashback_amount=round(txn.points_total / POINTS_PER_EURO, 2),
        new_balance=euro_value,
    )
