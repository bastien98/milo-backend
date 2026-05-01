import io
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_current_db_user
from app.config import get_settings
from app.db.repositories.brand_cashback_repo import BrandCashbackRepository
from app.models.user import User
from app.schemas.brand_cashback import (
    AdminCampaignCreate,
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
    claim = await svc.claim_deal(current_user.id, campaign_id)
    if claim is None:
        raise HTTPException(status_code=404, detail="Campaign not found or inactive")
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

    all_campaigns = await repo.get_all_campaigns()
    claims = await repo.get_user_claims(current_user.id)
    now = datetime.now(timezone.utc)

    result = []
    for campaign in all_campaigns:
        claim = claims.get(campaign.id)
        if not claim:
            continue
        if claim.status == "earned":
            result.append(
                BrandCashbackDealResponse(
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
                    user_status="earned",
                    earned_at=claim.earned_at,
                )
            )
        elif claim.status == "claimed" and campaign.is_active and campaign.valid_until > now:
            result.append(
                BrandCashbackDealResponse(
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
                    user_status="claimed",
                )
            )
    return result


# ---------------------------------------------------------------------------
# Admin endpoints
# ---------------------------------------------------------------------------


@router.get("/admin/campaigns", response_model=list[AdminCampaignResponse])
async def admin_list_campaigns(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
):
    _require_admin(current_user)
    repo = BrandCashbackRepository(db)
    campaigns = await repo.get_all_campaigns()

    result = []
    for c in campaigns:
        claims_count, earned_count = await repo.get_campaign_claim_counts(c.id)
        result.append(
            AdminCampaignResponse(
                id=c.id,
                brand_name=c.brand_name,
                product_name=c.product_name,
                description=c.description,
                cashback_amount_cents=c.cashback_amount_cents,
                image_url=image_url_for_key(c.image_s3_key),
                valid_from=c.valid_from,
                valid_until=c.valid_until,
                eligible_stores=c.eligible_stores or [],
                requires_store=c.requires_store,
                is_active=c.is_active,
                created_at=c.created_at,
                updated_at=c.updated_at,
                claims_count=claims_count,
                earned_count=earned_count,
            )
        )
    return result


@router.post("/admin/campaigns", response_model=AdminCampaignResponse, status_code=status.HTTP_201_CREATED)
async def admin_create_campaign(
    payload: AdminCampaignCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
):
    _require_admin(current_user)
    repo = BrandCashbackRepository(db)
    campaign = await repo.create_campaign(payload.model_dump())
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
        claims_count=0,
        earned_count=0,
    )


@router.patch("/admin/campaigns/{campaign_id}", response_model=AdminCampaignResponse)
async def admin_update_campaign(
    campaign_id: str,
    payload: AdminCampaignUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
):
    _require_admin(current_user)
    repo = BrandCashbackRepository(db)
    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    campaign = await repo.update_campaign(campaign_id, updates)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    claims_count, earned_count = await repo.get_campaign_claim_counts(campaign_id)
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
    )


@router.delete("/admin/campaigns/{campaign_id}", status_code=status.HTTP_204_NO_CONTENT)
async def admin_delete_campaign(
    campaign_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
):
    _require_admin(current_user)
    repo = BrandCashbackRepository(db)
    campaign = await repo.get_campaign_by_id(campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    # Soft-delete: deactivate instead of hard-delete to preserve earned claim history.
    await repo.update_campaign(campaign_id, {"is_active": False})


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
    claims_count, earned_count = await repo.get_campaign_claim_counts(campaign_id)

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
    )


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
