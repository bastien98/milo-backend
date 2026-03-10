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
    """Get all lottery entries for a month."""
    repo = LotteryRepository(db)
    drawing = await repo.get_drawing_by_month(month)
    if not drawing:
        return []
    entries = await repo.get_entries_for_drawing(drawing.id)
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


@router.get("/admin/drawings", response_model=list[LotteryDrawingResponse])
async def get_all_drawings(
    db: AsyncSession = Depends(get_db),
):
    """Get all lottery drawings."""
    repo = LotteryRepository(db)
    drawings = await repo.get_all_drawings()
    return drawings
