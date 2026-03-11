from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_current_db_user
from app.models.user import User
from app.schemas.lottery import (
    LotteryStatusResponse,
    LotteryDrawingResponse,
    LotteryEntryResponse,
    ToggleShareRequest,
    PublishRequest,
    ApproveProofRequest,
    VideoPropsResponse,
)
from app.services.lottery_service import LotteryService
from app.services.instagram_service import InstagramService
from app.db.repositories.lottery_repo import LotteryRepository

router = APIRouter()


# ── User-facing endpoints ──

@router.get("/status", response_model=LotteryStatusResponse)
async def get_lottery_status(
    current_user: User = Depends(get_current_db_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the current month's lottery eligibility status for the authenticated user."""
    svc = LotteryService(db)
    result = await svc.get_user_lottery_status(current_user.id, current_user.firebase_uid)
    return result


@router.post("/declare-share")
async def declare_share(
    current_user: User = Depends(get_current_db_user),
    db: AsyncSession = Depends(get_db),
):
    """User declares they shared the IG post. Sets status to pending_review for admin verification."""
    now = datetime.now(timezone.utc)
    current_month = f"{now.year}-{now.month:02d}"
    repo = LotteryRepository(db)
    drawing = await repo.get_or_create_drawing(current_month)

    if drawing.status != "pending":
        raise HTTPException(status_code=400, detail="Participants are already locked for this month")

    await repo.declare_share(drawing.id, current_user.id)
    await db.commit()

    return {"ok": True, "proof_status": "pending_review"}


# ── Admin endpoints ──

@router.post("/admin/drawing/{month}", response_model=LotteryDrawingResponse)
async def get_or_create_drawing(
    month: str,
    db: AsyncSession = Depends(get_db),
):
    """Get or create a lottery drawing for a given month (e.g., 2026-03)."""
    repo = LotteryRepository(db)
    drawing = await repo.get_or_create_drawing(month)
    await db.commit()
    return drawing


@router.get("/admin/drawing/{month}", response_model=LotteryDrawingResponse)
async def get_drawing(
    month: str,
    db: AsyncSession = Depends(get_db),
):
    """Get a lottery drawing for a given month."""
    repo = LotteryRepository(db)
    drawing = await repo.get_drawing_by_month(month)
    if not drawing:
        raise HTTPException(status_code=404, detail="Drawing not found")
    return drawing


@router.get("/admin/entries/{month}", response_model=list[LotteryEntryResponse])
async def get_entries(
    month: str,
    db: AsyncSession = Depends(get_db),
):
    """Get all lottery entries for a month, auto-populating from Gold Tier users."""
    svc = LotteryService(db)
    entries = await svc.refresh_entries(month)
    return entries


@router.post("/admin/sync-mentions")
async def sync_instagram_mentions(
    db: AsyncSession = Depends(get_db),
):
    """Sync Instagram mentions and update lottery entries."""
    ig_service = InstagramService()

    if not ig_service.is_configured:
        return {"synced_count": 0, "message": "Instagram API not configured. Use manual toggle instead."}

    mentions = await ig_service.get_mentions()
    handles = ig_service.extract_handles_from_mentions(mentions)

    # Cross-reference with user profiles and update entries
    from sqlalchemy import select
    from app.models.user_profile import UserProfile
    from app.models.user import User
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    current_month = f"{now.year}-{now.month:02d}"
    repo = LotteryRepository(db)
    drawing = await repo.get_or_create_drawing(current_month)

    synced = 0
    for handle in handles:
        result = await db.execute(
            select(UserProfile, User)
            .join(User, User.firebase_uid == UserProfile.user_id)
            .where(UserProfile.instagram_handle.ilike(handle))
        )
        row = result.first()
        if row:
            profile, user = row
            entry_result = await db.execute(
                select(LotteryEntry)
                .where(
                    LotteryEntry.drawing_id == drawing.id,
                    LotteryEntry.user_id == user.id,
                )
            )
            from app.models.lottery import LotteryEntry
            entry = entry_result.scalar_one_or_none()
            if entry:
                entry.has_instagram_share = True
                entry.is_eligible = entry.has_receipt_activity and True
            else:
                await repo.upsert_entry(
                    drawing_id=drawing.id,
                    user_id=user.id,
                    instagram_handle=profile.instagram_handle,
                    display_name=profile.nickname or profile.first_name or "User",
                    has_receipt_activity=False,
                    has_instagram_share=True,
                )
            synced += 1

    await db.commit()
    return {"synced_count": synced}


@router.post("/admin/toggle-share/{month}")
async def toggle_share(
    month: str,
    data: ToggleShareRequest,
    db: AsyncSession = Depends(get_db),
):
    """Manually toggle IG share status for a user."""
    repo = LotteryRepository(db)
    drawing = await repo.get_drawing_by_month(month)
    if not drawing:
        raise HTTPException(status_code=404, detail="Drawing not found")

    await repo.toggle_share(drawing.id, data.user_id, data.shared)
    await db.commit()
    return {"ok": True}


@router.post("/admin/lock/{month}", response_model=LotteryDrawingResponse)
async def lock_participants(
    month: str,
    db: AsyncSession = Depends(get_db),
):
    """Lock participants for a month's drawing."""
    svc = LotteryService(db)
    try:
        drawing = await svc.lock_participants(month)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    return drawing


@router.post("/admin/draw/{month}", response_model=LotteryDrawingResponse)
async def draw_winner(
    month: str,
    db: AsyncSession = Depends(get_db),
):
    """Draw a winner for a month's lottery."""
    svc = LotteryService(db)
    try:
        drawing = await svc.draw_winner(month)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    return drawing


@router.get("/admin/video-props/{month}", response_model=VideoPropsResponse)
async def get_video_props(
    month: str,
    db: AsyncSession = Depends(get_db),
):
    """Get Remotion video props for a drawn lottery."""
    svc = LotteryService(db)
    try:
        props = await svc.get_video_props(month)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return props


@router.post("/admin/publish/{month}", response_model=LotteryDrawingResponse)
async def publish_drawing(
    month: str,
    data: PublishRequest,
    db: AsyncSession = Depends(get_db),
):
    """Mark a drawing as published with the video URL."""
    svc = LotteryService(db)
    try:
        drawing = await svc.publish_drawing(month, data.video_url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    return drawing


@router.post("/admin/approve-proof/{entry_id}")
async def approve_proof(
    entry_id: str,
    data: ApproveProofRequest,
    db: AsyncSession = Depends(get_db),
):
    """Approve or reject a user's IG share declaration after manual verification."""
    repo = LotteryRepository(db)
    entry = await repo.get_entry_by_id(entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")

    await repo.approve_proof(entry_id, data.approved)
    await db.commit()
    return {"ok": True, "proof_status": "approved" if data.approved else "rejected"}


@router.get("/admin/drawings", response_model=list[LotteryDrawingResponse])
async def get_all_drawings(
    db: AsyncSession = Depends(get_db),
):
    """Get all lottery drawings."""
    repo = LotteryRepository(db)
    drawings = await repo.get_all_drawings()
    return drawings


@router.post("/admin/seed-test/{month}")
async def seed_test_entries(
    month: str,
    db: AsyncSession = Depends(get_db),
):
    """Seed fake test participants for testing the full lottery flow."""
    repo = LotteryRepository(db)
    drawing = await repo.get_or_create_drawing(month)

    if drawing.status != "pending":
        raise HTTPException(status_code=400, detail="Drawing is not in pending state. Reset first.")

    import uuid

    test_participants = [
        ("Emma De Smedt", "emma.ds"),
        ("Lucas Peeters", "lucas_p"),
        ("Sophie Janssen", "sophiej"),
        ("Noah Willems", "noah.w"),
        ("Olivia Maes", "olivia.maes"),
        ("Liam Claes", "liam.c"),
        ("Charlotte Dubois", "charlotte.db"),
        ("Arthur Vermeersch", "arthur.v"),
    ]

    for name, handle in test_participants:
        test_user_id = f"test-{uuid.uuid5(uuid.NAMESPACE_DNS, handle)}"
        await repo.upsert_entry(
            drawing_id=drawing.id,
            user_id=test_user_id,
            instagram_handle=handle,
            display_name=name,
            has_receipt_activity=True,
            has_instagram_share=True,
        )

    await db.commit()
    return {"ok": True, "seeded": len(test_participants)}


@router.post("/admin/reset/{month}")
async def reset_drawing(
    month: str,
    db: AsyncSession = Depends(get_db),
):
    """Reset a drawing back to pending state, removing all entries."""
    from sqlalchemy import delete
    from app.models.lottery import LotteryEntry

    repo = LotteryRepository(db)
    drawing = await repo.get_drawing_by_month(month)
    if not drawing:
        raise HTTPException(status_code=404, detail="Drawing not found")

    await db.execute(
        delete(LotteryEntry).where(LotteryEntry.drawing_id == drawing.id)
    )
    await repo.update_drawing(
        drawing,
        status="pending",
        seed=None,
        seed_hash=None,
        winner_user_id=None,
        winner_name=None,
        winner_instagram_handle=None,
        participant_count=0,
        video_url=None,
        drawn_at=None,
        published_at=None,
    )
    await db.commit()
    return {"ok": True}
