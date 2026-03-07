import os

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_current_db_user
from app.models.user import User
from app.services.withdrawal_service import WithdrawalService
from app.schemas.withdrawal import (
    WithdrawalCreateRequest,
    WithdrawalInfoResponse,
    WithdrawalCreateResponse,
    WithdrawalHistoryResponse,
    WithdrawalResponse,
    WithdrawalAdminReviewRequest,
    WithdrawalAdminListItem,
)

router = APIRouter()

ADMIN_EMAILS = [e.strip() for e in os.getenv("ADMIN_EMAILS", "").split(",") if e.strip()]
TEST_MODE = os.getenv("WITHDRAWAL_TEST_MODE", "false").lower() == "true"


async def require_admin(current_user: User = Depends(get_current_db_user)):
    if not current_user.email or current_user.email not in ADMIN_EMAILS:
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user


# ────────────────── User endpoints ──────────────────


@router.get("/info", response_model=WithdrawalInfoResponse)
async def get_withdrawal_info(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
):
    """Get withdrawal eligibility info: balance, amounts, pending status."""
    svc = WithdrawalService(db)
    info = await svc.get_withdrawal_info(current_user)
    return info


@router.post("/request", response_model=WithdrawalCreateResponse)
async def create_withdrawal(
    body: WithdrawalCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
):
    """Create a new withdrawal request."""
    svc = WithdrawalService(db)
    try:
        result = await svc.create_withdrawal(current_user, body.amount, body.iban)
        await db.commit()
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/history", response_model=WithdrawalHistoryResponse)
async def get_withdrawal_history(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
):
    """Get user's withdrawal history."""
    svc = WithdrawalService(db)
    withdrawals = await svc.get_user_withdrawals(current_user.id)
    has_pending = any(
        w.status.value in ("pending_review", "auto_approved", "approved")
        for w in withdrawals
    )
    return WithdrawalHistoryResponse(
        withdrawals=[
            WithdrawalResponse.model_validate(w) for w in withdrawals
        ],
        has_pending=has_pending,
    )


# ────────────────── Admin endpoints ──────────────────


def _to_admin_item(w: "WithdrawalRequest") -> WithdrawalAdminListItem:
    return WithdrawalAdminListItem(
        id=w.id,
        user_id=w.user_id,
        user_email=w.user.email if w.user else None,
        amount=w.amount,
        iban=w.iban,
        iban_last4=w.iban_last4,
        status=w.status,
        fraud_check_passed=w.fraud_check_passed,
        fraud_check_details=w.fraud_check_details,
        admin_notes=w.admin_notes,
        created_at=w.created_at,
        reviewed_at=w.reviewed_at,
        paid_out_at=w.paid_out_at,
    )


@router.get("/admin/pending", response_model=list[WithdrawalAdminListItem])
async def get_pending_withdrawals(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """Admin: list all pending withdrawal requests."""
    svc = WithdrawalService(db)
    withdrawals = await svc.get_all_pending()
    return [_to_admin_item(w) for w in withdrawals]


@router.get("/admin/actionable", response_model=list[WithdrawalAdminListItem])
async def get_actionable_withdrawals(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """Admin: list all withdrawals needing action (pending, approved, awaiting payout)."""
    svc = WithdrawalService(db)
    withdrawals = await svc.get_all_actionable()
    return [_to_admin_item(w) for w in withdrawals]


@router.get("/admin/all", response_model=list[WithdrawalAdminListItem])
async def get_all_withdrawals(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """Admin: list all withdrawals across all users."""
    svc = WithdrawalService(db)
    withdrawals = await svc.get_all_withdrawals()
    return [_to_admin_item(w) for w in withdrawals]


@router.post("/admin/{withdrawal_id}/review")
async def review_withdrawal(
    withdrawal_id: str,
    body: WithdrawalAdminReviewRequest,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """Admin: approve or reject a withdrawal."""
    svc = WithdrawalService(db)
    try:
        if body.action == "approve":
            withdrawal = await svc.approve_withdrawal(withdrawal_id, body.admin_notes)
        elif body.action == "reject":
            withdrawal = await svc.reject_withdrawal(withdrawal_id, body.admin_notes)
        else:
            raise HTTPException(status_code=400, detail="Action must be 'approve' or 'reject'")
        await db.commit()
        return WithdrawalResponse.model_validate(withdrawal)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/admin/{withdrawal_id}/paid")
async def mark_paid_out(
    withdrawal_id: str,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """Admin: mark an approved withdrawal as paid out."""
    svc = WithdrawalService(db)
    try:
        withdrawal = await svc.mark_paid_out(withdrawal_id)
        await db.commit()
        return WithdrawalResponse.model_validate(withdrawal)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ────────────────── Test endpoints ──────────────────


@router.post("/test/auto-process/{withdrawal_id}")
async def test_auto_process(
    withdrawal_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
):
    """Test mode: auto-process a withdrawal through approve -> paid_out."""
    if not TEST_MODE:
        raise HTTPException(status_code=403, detail="Test mode is not enabled")
    svc = WithdrawalService(db)
    try:
        withdrawal = await svc.test_auto_process(withdrawal_id)
        await db.commit()
        return WithdrawalResponse.model_validate(withdrawal)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/test/reset")
async def test_reset(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
):
    """Test mode: delete all withdrawals for the current user and refund balances."""
    if not TEST_MODE:
        raise HTTPException(status_code=403, detail="Test mode is not enabled")
    svc = WithdrawalService(db)
    try:
        count = await svc.test_reset(current_user.id)
        await db.commit()
        return {"deleted": count, "message": f"Deleted {count} withdrawal(s) and refunded balances"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
