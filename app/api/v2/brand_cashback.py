import io
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_current_db_user
from app.config import get_settings
from app.db.repositories.brand_cashback_repo import BrandCashbackRepository
from app.models.brand_cashback import BrandCashbackCampaign
from app.models.user import User
from app.schemas.brand_cashback import (
    AdminCampaignCreate,
    AdminCampaignDeletePreview,
    AdminCampaignResponse,
    AdminCampaignUpdate,
    AdminLineItemCreate,
    AdminLineItemResponse,
    AdminStatsResponse,
    BrandCashbackClaimResponse,
    BrandCashbackDealResponse,
)
from app.services.brand_cashback_service import (
    BrandCashbackService,
    campaign_to_deal_response,
    image_url_for_key,
    storage,
)

router = APIRouter()

ALLOWED_IMAGE_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_IMAGE_BYTES = 10 * 1024 * 1024  # 10 MB raw input
MAX_IMAGE_DIMENSION = 800
JPEG_QUALITY = 85


def _optimize_campaign_image(content: bytes) -> bytes:
    """Decode, EXIF-rotate, downscale to ≤800px, re-encode as JPEG q85."""
    try:
        img = Image.open(io.BytesIO(content))
        img = ImageOps.exif_transpose(img)
        if img.mode != "RGB":
            img = img.convert("RGB")
        img.thumbnail((MAX_IMAGE_DIMENSION, MAX_IMAGE_DIMENSION), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=True)
        return buf.getvalue()
    except (UnidentifiedImageError, OSError) as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Could not decode image: {e}",
        )


def _require_admin(current_user: User) -> None:
    settings = get_settings()
    admin_uids: list[str] = getattr(settings, "ADMIN_UIDS", [])
    if current_user.firebase_uid not in admin_uids:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only")


async def _build_admin_response(
    campaign: BrandCashbackCampaign,
    repo: BrandCashbackRepository,
) -> AdminCampaignResponse:
    """Build the full admin response for a campaign, including derived fields."""
    claims_count, earned_count = await repo.get_campaign_claim_counts(campaign.id)
    eligible_skus = await repo.get_distinct_exact_line_items(campaign.id)
    return AdminCampaignResponse(
        id=campaign.id,
        brand_name=campaign.brand_name,
        product_name=campaign.product_name,
        description=campaign.description,
        cashback_amount_cents=campaign.cashback_amount_cents,
        image_url=image_url_for_key(campaign.image_s3_key),
        valid_from=campaign.valid_from,
        valid_until=campaign.valid_until,
        eligible_stores=campaign.eligible_stores or [],
        requires_store=campaign.requires_store,
        is_active=campaign.is_active,
        created_at=campaign.created_at,
        updated_at=campaign.updated_at,
        claims_count=claims_count,
        earned_count=earned_count,
        terms=campaign.terms,
        how_it_works=campaign.how_it_works or [],
        claim_window_days=campaign.claim_window_days,
        max_redemptions_per_user=campaign.max_redemptions_per_user,
        total_redemption_cap=campaign.total_redemption_cap,
        category=campaign.category,
        featured=campaign.featured,
        current_redemptions=earned_count,
        eligible_skus=eligible_skus,
    )


# ---------------------------------------------------------------------------
# User endpoints
# ---------------------------------------------------------------------------


@router.get("/deals", response_model=list[BrandCashbackDealResponse])
async def get_deals(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
):
    """Active cashback deals with the user's personal claim status."""
    svc = BrandCashbackService(db)
    return await svc.get_deals_for_user(current_user.id)


@router.post("/claim/{campaign_id}", response_model=BrandCashbackClaimResponse)
async def claim_deal(
    campaign_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
):
    """Claim a cashback deal before uploading a receipt."""
    svc = BrandCashbackService(db)
    claim, error = await svc.claim_deal(current_user.id, campaign_id)
    if error == "not_found":
        raise HTTPException(status_code=404, detail="Campaign not found or inactive")
    if error == "user_limit_reached":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You have reached the per-user redemption limit for this campaign",
        )
    if error == "campaign_full":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This campaign has reached its total redemption cap",
        )
    return BrandCashbackClaimResponse(
        campaign_id=claim.campaign_id,
        status=claim.status,
        claimed_at=claim.claimed_at,
    )


@router.delete("/claim/{campaign_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unclaim_deal(
    campaign_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
):
    """Remove a claimed deal (only if not yet matched)."""
    svc = BrandCashbackService(db)
    deleted = await svc.unclaim_deal(current_user.id, campaign_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Claim not found or already earned")


@router.get("/my-claims", response_model=list[BrandCashbackDealResponse])
async def get_my_claims(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
):
    """
    Deals the user has claimed or earned.
    - 'earned' claims: returned for ALL campaigns (including inactive/deleted-soft ones)
      so that earned history is never lost.
    - 'claimed' claims: only returned for still-active, non-expired campaigns.
    """
    repo = BrandCashbackRepository(db)

    all_campaigns = await repo.get_all_campaigns(include_inactive=True)
    claims = await repo.get_user_claims(current_user.id)
    now = datetime.now(timezone.utc)

    result = []
    for campaign in all_campaigns:
        claim = claims.get(campaign.id)
        if not claim:
            continue
        is_earned = claim.status == "earned"
        is_active_claim = (
            claim.status == "claimed" and campaign.is_active and campaign.valid_until > now
        )
        if not (is_earned or is_active_claim):
            continue

        _, earned_count = await repo.get_campaign_claim_counts(campaign.id)
        eligible_skus = await repo.get_distinct_exact_line_items(campaign.id)
        claim_expires_at = None
        if is_active_claim:
            claim_expires_at = claim.claimed_at + timedelta(days=campaign.claim_window_days)

        result.append(
            campaign_to_deal_response(
                campaign,
                "earned" if is_earned else "claimed",
                current_redemptions=earned_count,
                eligible_skus=eligible_skus,
                claim_expires_at=claim_expires_at,
                earned_at=claim.earned_at if is_earned else None,
            )
        )
    return result


# ---------------------------------------------------------------------------
# Admin endpoints
# ---------------------------------------------------------------------------


@router.get("/admin/campaigns", response_model=list[AdminCampaignResponse])
async def admin_list_campaigns(
    include_inactive: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
):
    _require_admin(current_user)
    repo = BrandCashbackRepository(db)
    campaigns = await repo.get_all_campaigns(include_inactive=include_inactive)
    return [await _build_admin_response(c, repo) for c in campaigns]


@router.post("/admin/campaigns", response_model=AdminCampaignResponse, status_code=status.HTTP_201_CREATED)
async def admin_create_campaign(
    payload: AdminCampaignCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
):
    _require_admin(current_user)
    repo = BrandCashbackRepository(db)
    campaign = await repo.create_campaign(payload.model_dump())
    return await _build_admin_response(campaign, repo)


@router.patch("/admin/campaigns/{campaign_id}", response_model=AdminCampaignResponse)
async def admin_update_campaign(
    campaign_id: str,
    payload: AdminCampaignUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
):
    _require_admin(current_user)
    repo = BrandCashbackRepository(db)
    existing = await repo.get_campaign_by_id(campaign_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Campaign not found")

    updates = payload.model_dump(exclude_unset=True)

    # Validate date order against the merged state (touched values + untouched existing).
    new_from = updates.get("valid_from", existing.valid_from)
    new_until = updates.get("valid_until", existing.valid_until)
    if new_until <= new_from:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="valid_until must be after valid_from",
        )

    campaign = await repo.update_campaign(campaign_id, updates)
    return await _build_admin_response(campaign, repo)


@router.get(
    "/admin/campaigns/{campaign_id}/delete-preview",
    response_model=AdminCampaignDeletePreview,
)
async def admin_delete_preview(
    campaign_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
):
    """Tells the admin UI whether a delete will hard- or soft-delete the campaign."""
    _require_admin(current_user)
    repo = BrandCashbackRepository(db)
    campaign = await repo.get_campaign_by_id(campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    _, earned_count = await repo.get_campaign_claim_counts(campaign_id)
    return AdminCampaignDeletePreview(
        earned_count=earned_count,
        would_hard_delete=earned_count == 0,
    )


@router.delete("/admin/campaigns/{campaign_id}", status_code=status.HTTP_204_NO_CONTENT)
async def admin_delete_campaign(
    campaign_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
):
    """
    Smart delete. Hard-deletes (campaign + cascading line items + claims + S3 image)
    when no earned claims exist. Soft-deletes (preserves earned history, deletes S3
    image) when at least one user has earned the cashback.
    """
    _require_admin(current_user)
    repo = BrandCashbackRepository(db)
    campaign = await repo.get_campaign_by_id(campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    _, earned_count = await repo.get_campaign_claim_counts(campaign_id)

    if campaign.image_s3_key:
        storage.delete(campaign.image_s3_key)

    if earned_count == 0:
        # Hard-delete; cascade="all, delete-orphan" on the model removes line items + claims.
        await repo.delete_campaign(campaign_id)
    else:
        # Preserve earned history; clear the S3 key so future reads don't try to fetch a deleted object.
        await repo.update_campaign(
            campaign_id, {"is_active": False, "image_s3_key": None}
        )


@router.post("/admin/campaigns/{campaign_id}/image", response_model=AdminCampaignResponse)
async def admin_upload_campaign_image(
    campaign_id: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
):
    _require_admin(current_user)
    repo = BrandCashbackRepository(db)
    campaign = await repo.get_campaign_by_id(campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    content_type = file.content_type or "application/octet-stream"
    if content_type not in ALLOWED_IMAGE_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Only JPEG, PNG, and WebP images are supported, got: {content_type}",
        )

    content = await file.read()
    if len(content) > MAX_IMAGE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Image exceeds {MAX_IMAGE_BYTES // (1024 * 1024)}MB limit",
        )

    optimized = _optimize_campaign_image(content)

    if campaign.image_s3_key:
        storage.delete(campaign.image_s3_key)

    new_key = storage.upload_campaign_image(campaign_id, optimized, "jpg")
    campaign = await repo.update_campaign(campaign_id, {"image_s3_key": new_key})
    return await _build_admin_response(campaign, repo)


@router.post(
    "/admin/campaigns/{campaign_id}/line-items",
    response_model=AdminLineItemResponse,
    status_code=status.HTTP_201_CREATED,
)
async def admin_add_line_item(
    campaign_id: str,
    payload: AdminLineItemCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
):
    _require_admin(current_user)
    repo = BrandCashbackRepository(db)
    campaign = await repo.get_campaign_by_id(campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    data = payload.model_dump()
    data["campaign_id"] = campaign_id
    item = await repo.create_line_item(data)
    return AdminLineItemResponse(
        id=item.id,
        campaign_id=item.campaign_id,
        store_name=item.store_name,
        exact_line_item=item.exact_line_item,
        alt_line_items=item.alt_line_items or [],
        notes=item.notes,
        verified_at=item.verified_at,
        created_at=item.created_at,
    )


@router.get(
    "/admin/campaigns/{campaign_id}/line-items",
    response_model=list[AdminLineItemResponse],
)
async def admin_list_line_items(
    campaign_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
):
    _require_admin(current_user)
    repo = BrandCashbackRepository(db)
    items = await repo.get_line_items_for_campaign(campaign_id)
    return [
        AdminLineItemResponse(
            id=i.id,
            campaign_id=i.campaign_id,
            store_name=i.store_name,
            exact_line_item=i.exact_line_item,
            alt_line_items=i.alt_line_items or [],
            notes=i.notes,
            verified_at=i.verified_at,
            created_at=i.created_at,
        )
        for i in items
    ]


@router.patch("/admin/line-items/{line_item_id}", response_model=AdminLineItemResponse)
async def admin_update_line_item(
    line_item_id: str,
    payload: AdminLineItemCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
):
    _require_admin(current_user)
    repo = BrandCashbackRepository(db)
    item = await repo.update_line_item(line_item_id, payload.model_dump())
    if not item:
        raise HTTPException(status_code=404, detail="Line item not found")
    return AdminLineItemResponse(
        id=item.id,
        campaign_id=item.campaign_id,
        store_name=item.store_name,
        exact_line_item=item.exact_line_item,
        alt_line_items=item.alt_line_items or [],
        notes=item.notes,
        verified_at=item.verified_at,
        created_at=item.created_at,
    )


@router.delete("/admin/line-items/{line_item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def admin_delete_line_item(
    line_item_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
):
    _require_admin(current_user)
    repo = BrandCashbackRepository(db)
    item = await repo.get_line_item_by_id(line_item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Line item not found")
    await repo.delete_line_item(line_item_id)


@router.get("/admin/stats", response_model=AdminStatsResponse)
async def admin_get_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
):
    _require_admin(current_user)
    repo = BrandCashbackRepository(db)
    stats = await repo.get_global_stats()
    return AdminStatsResponse(**stats)
