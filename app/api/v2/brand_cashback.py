import io
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from PIL import Image, ImageChops, ImageOps, UnidentifiedImageError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_current_db_user
from app.config import get_settings
from app.db.repositories.brand_cashback_repo import BrandCashbackRepository
from app.models.brand_cashback import BrandCashbackCampaign, BrandCashbackPendingMatch
from app.models.user import User
from app.schemas.brand_cashback import (
    AdminApprovePendingRequest,
    AdminCampaignCreate,
    AdminCampaignDeletePreview,
    AdminCampaignResponse,
    AdminCampaignUpdate,
    AdminCodeProposalResponse,
    AdminDenyPendingRequest,
    AdminLineItemCreate,
    AdminLineItemResponse,
    AdminRejectCodeProposalRequest,
    AdminStatsResponse,
    BrandCashbackClaimResponse,
    BrandCashbackDealResponse,
    BrandCashbackPendingMatchResponse,
    BrandCashbackWalletResponse,
)
from app.services.brand_cashback_service import (
    APPROVE_ALREADY_REVIEWED,
    APPROVE_CAMPAIGN_EXPIRED,
    APPROVE_CAMPAIGN_FULL,
    APPROVE_CAMPAIGN_INACTIVE,
    APPROVE_NOT_FOUND,
    APPROVE_RECEIPT_OUTSIDE,
    APPROVE_USER_LIMIT,
    BrandCashbackService,
    DENIAL_BANNER_TTL,
    _to_denial_summary,
    _to_pending_summary,
    campaign_to_deal_response,
    image_url_for_key,
    storage,
)
from app.services.brand_cashback_wallet_service import BrandCashbackWalletService

router = APIRouter()

ALLOWED_IMAGE_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_IMAGE_BYTES = 10 * 1024 * 1024  # 10 MB raw input
MIN_SOURCE_DIMENSION = 600  # reject sources smaller than this on the short edge
HERO_MAX_DIMENSION = 1200
THUMB_DIMENSION = 400  # 400x400 square — fit-with-pad, never crop
THUMB_PAD_RGB = (255, 255, 255)  # matches the white photo tile in the iOS card
BRAND_LOGO_MAX_DIMENSION = 512
JPEG_QUALITY = 85


def _decode_image(content: bytes) -> Image.Image:
    try:
        img = Image.open(io.BytesIO(content))
        img = ImageOps.exif_transpose(img)
        if img.mode != "RGB":
            img = img.convert("RGB")
        return img
    except (UnidentifiedImageError, OSError) as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Could not decode image: {e}",
        )


def _decode_image_keep_alpha(content: bytes) -> Image.Image:
    """Decode preserving alpha channel — used for brand logos which often
    have transparent backgrounds and shouldn't be flattened to RGB."""
    try:
        img = Image.open(io.BytesIO(content))
        img = ImageOps.exif_transpose(img)
        if img.mode == "P":
            img = img.convert("RGBA" if "transparency" in img.info else "RGB")
        elif img.mode not in ("RGB", "RGBA", "LA"):
            img = img.convert("RGBA")
        return img
    except (UnidentifiedImageError, OSError) as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Could not decode image: {e}",
        )


def _make_brand_logo(img: Image.Image) -> tuple[bytes, str]:
    """Normalize a brand logo for the iOS card's white disc.

    Always outputs an opaque JPEG with a pure-white surround so the image
    composites flush onto `Circle().fill(.white)` — both whites match exactly,
    no visible seam, no faint anti-aliased fringe.

    Pipeline:
      1. Flatten any alpha onto a pure-white background. Transparent PNGs
         become opaque RGB so the output is always JPEG / single code path.
      2. Snap near-white pixels (R, G, B all >= 235) to pure (255, 255, 255).
         Collapses both off-white source backgrounds (e.g. `#FAFAFA`) and
         anti-aliased edge halos into the same exact white as the iOS disc.
      3. Trim pure-white margins so the logo content always fills the canvas.
         `ImageOps.invert(...).getbbox()` flips pure-white to pure-black, then
         `getbbox()` returns the smallest box containing every non-pure-white
         pixel — i.e. the logo. Works for any future upload: tightly cropped
         logos no-op (bbox is full canvas), padded logos auto-fit.
      4. Pad to a square white canvas so wide wordmarks stay centred (don't
         end up as a thin sliver inside the circular disc).
      5. Resize to max 512px on the long edge.
    """
    out = img.copy()

    # 1. Flatten alpha onto white.
    if out.mode == "LA":
        out = out.convert("RGBA")
    if out.mode == "RGBA":
        bg = Image.new("RGB", out.size, (255, 255, 255))
        bg.paste(out, mask=out.split()[-1])
        out = bg
    elif out.mode != "RGB":
        out = out.convert("RGB")

    # 2. Snap near-white pixels to pure white. Threshold each channel to a
    # 0/255 mask, then AND the three masks together via ImageChops.multiply
    # (255*255/255 = 255 only where all three pass). Pixels where every
    # channel >= NEAR_WHITE_THRESHOLD become exact white. 235 catches the
    # typical cream-tinted backgrounds (e.g. R244 G243 B238) brands ship,
    # while leaving genuine logo content (sub-235 grays) untouched.
    NEAR_WHITE_THRESHOLD = 235
    r, g, b = out.split()
    r_pass = r.point(lambda v: 255 if v >= NEAR_WHITE_THRESHOLD else 0)
    g_pass = g.point(lambda v: 255 if v >= NEAR_WHITE_THRESHOLD else 0)
    b_pass = b.point(lambda v: 255 if v >= NEAR_WHITE_THRESHOLD else 0)
    near_white_mask = ImageChops.multiply(
        ImageChops.multiply(r_pass, g_pass), b_pass
    )
    pure_white = Image.new("RGB", out.size, (255, 255, 255))
    out = Image.composite(pure_white, out, near_white_mask)

    # 3. Trim pure-white margins so the logo content fills the canvas.
    bbox = ImageOps.invert(out).getbbox()
    if bbox:
        out = out.crop(bbox)

    # 4. Pad to a square white canvas.
    side = max(out.width, out.height)
    if side > 0 and (out.width != side or out.height != side):
        canvas = Image.new("RGB", (side, side), (255, 255, 255))
        offset = ((side - out.width) // 2, (side - out.height) // 2)
        canvas.paste(out, offset)
        out = canvas

    # 4. Resize.
    out.thumbnail(
        (BRAND_LOGO_MAX_DIMENSION, BRAND_LOGO_MAX_DIMENSION), Image.LANCZOS
    )

    buf = io.BytesIO()
    out.save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    return buf.getvalue(), "jpg"


def _encode_jpeg(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    return buf.getvalue()


def _make_hero(img: Image.Image) -> bytes:
    """Hero variant: preserves original aspect, max 1200px on the long edge."""
    out = img.copy()
    out.thumbnail((HERO_MAX_DIMENSION, HERO_MAX_DIMENSION), Image.LANCZOS)
    return _encode_jpeg(out)


def _make_thumb(img: Image.Image) -> bytes:
    """Thumbnail variant: 400x400 fit-and-padded square — drives the grid card.

    Resizes the source so its long edge lands on THUMB_DIMENSION, then pastes
    it centered onto a THUMB_PAD_RGB canvas. The whole product is always
    visible; padding fills any non-square slack and matches the iOS card
    surface so it blends in.
    """
    fitted = img.copy()
    fitted.thumbnail((THUMB_DIMENSION, THUMB_DIMENSION), Image.LANCZOS)
    canvas = Image.new("RGB", (THUMB_DIMENSION, THUMB_DIMENSION), THUMB_PAD_RGB)
    offset = (
        (THUMB_DIMENSION - fitted.width) // 2,
        (THUMB_DIMENSION - fitted.height) // 2,
    )
    canvas.paste(fitted, offset)
    return _encode_jpeg(canvas)


def _require_admin(current_user: User) -> None:
    settings = get_settings()
    admin_uids: list[str] = getattr(settings, "ADMIN_UIDS", [])
    if current_user.firebase_uid not in admin_uids:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only")


def _line_item_to_response(item) -> AdminLineItemResponse:
    return AdminLineItemResponse(
        id=item.id,
        campaign_id=item.campaign_id,
        store_name=item.store_name,
        exact_line_item=item.exact_line_item,
        alt_line_items=item.alt_line_items or [],
        product_codes=item.product_codes or [],
        notes=item.notes,
        verified_at=item.verified_at,
        created_at=item.created_at,
    )


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
        image_thumb_url=image_url_for_key(campaign.image_thumb_s3_key),
        brand_logo_url=image_url_for_key(campaign.brand_logo_s3_key),
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
    """Claim a cashback deal. Idempotent: claiming twice returns the same record."""
    svc = BrandCashbackService(db)
    claim, error = await svc.claim_deal(current_user.id, campaign_id)
    if error == "not_found":
        raise HTTPException(status_code=404, detail="Campaign not found or inactive")
    if error == "expired":
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="Campaign has expired")
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
        claimed_at=claim.claimed_at,
    )


@router.delete("/claim/{campaign_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unclaim_deal(
    campaign_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
):
    """Remove the user's claim for a deal. Earnings already credited are preserved."""
    svc = BrandCashbackService(db)
    deleted = await svc.unclaim_deal(current_user.id, campaign_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Claim not found")


@router.get("/my-claims", response_model=list[BrandCashbackDealResponse])
async def get_my_claims(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
):
    """Deals the user has claimed and/or earned.

    Includes campaigns the user has any relationship with (a claim, earnings, or
    both), even if the campaign is inactive or expired — earned history is never
    hidden. The `user_status` is "earned" once earnings reach
    max_redemptions_per_user, otherwise "claimed".
    """
    repo = BrandCashbackRepository(db)

    all_campaigns = await repo.get_all_campaigns(include_inactive=True)
    claims = await repo.get_user_claims_by_campaign(current_user.id)
    earnings = await repo.get_user_earnings_by_campaign(current_user.id)
    pendings = {
        p.campaign_id: p
        for p in await repo.get_pending_matches_for_user(current_user.id, status="pending")
    }
    denials = {
        d.campaign_id: d
        for d in await repo.get_recent_denials_for_user(
            current_user.id, datetime.now(timezone.utc) - DENIAL_BANNER_TTL
        )
    }

    result = []
    for campaign in all_campaigns:
        user_earnings = earnings.get(campaign.id, [])
        claim = claims.get(campaign.id)
        pending = pendings.get(campaign.id)
        denial = denials.get(campaign.id)
        if not user_earnings and not claim and not pending and not denial:
            continue

        _, campaign_earnings = await repo.get_campaign_claim_counts(campaign.id)
        eligible_skus = await repo.get_distinct_exact_line_items(campaign.id)

        earnings_count = len(user_earnings)
        if earnings_count >= campaign.max_redemptions_per_user:
            user_status = "earned"
        else:
            user_status = "claimed"

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


def _pending_to_response(
    p: BrandCashbackPendingMatch,
    *,
    include_admin_context: bool = False,
) -> BrandCashbackPendingMatchResponse:
    """Map a pending row → API response. With include_admin_context, attach the
    campaign metadata, canonical line-item strings and a presigned receipt URL
    so the admin page can render the diff + image without extra round trips."""
    response = BrandCashbackPendingMatchResponse(
        id=p.id,
        user_id=p.user_id,
        campaign_id=p.campaign_id,
        receipt_id=p.receipt_id,
        candidate_string=p.candidate_string,
        matched_line_item_id=p.matched_line_item_id,
        match_score=p.match_score,
        store_name=p.store_name,
        status=p.status,
        created_at=p.created_at,
        reviewed_at=p.reviewed_at,
        reviewed_by=p.reviewed_by,
        denial_reason=p.denial_reason,
        earning_id=p.earning_id,
    )
    if include_admin_context:
        if p.campaign:
            response.brand_name = p.campaign.brand_name
            response.product_name = p.campaign.product_name
            response.cashback_amount_cents = p.campaign.cashback_amount_cents
        if p.matched_line_item:
            response.canonical_line_item = p.matched_line_item.exact_line_item
            response.canonical_alts = list(p.matched_line_item.alt_line_items or [])
        if p.receipt and getattr(p.receipt, "storage_key", None):
            response.receipt_image_url = image_url_for_key(p.receipt.storage_key)
    return response


@router.get(
    "/my-pending-reviews",
    response_model=list[BrandCashbackPendingMatchResponse],
)
async def get_my_pending_reviews(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
):
    """Pending admin reviews for receipts the user uploaded. Read-only."""
    repo = BrandCashbackRepository(db)
    rows = await repo.get_pending_matches_for_user(current_user.id, status="pending")
    return [_pending_to_response(p) for p in rows]


@router.get("/wallet", response_model=BrandCashbackWalletResponse)
async def get_wallet(
    earnings_limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
):
    """Brand cashback wallet snapshot: balance + recent earnings.

    `balance_cents` is what the user can withdraw right now. `total_earned_cents`
    and `total_withdrawn_cents` are lifetime audit counters. `recent_earnings`
    is newest-first, capped by `earnings_limit`.
    """
    svc = BrandCashbackWalletService(db)
    return await svc.get_wallet(current_user.id, earnings_limit=earnings_limit)


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
    if campaign.image_thumb_s3_key:
        storage.delete(campaign.image_thumb_s3_key)
    if campaign.brand_logo_s3_key:
        storage.delete(campaign.brand_logo_s3_key)

    if earned_count == 0:
        # Hard-delete; cascade="all, delete-orphan" on the model removes line items + claims.
        await repo.delete_campaign(campaign_id)
    else:
        # Preserve earned history; clear S3 keys so future reads don't try to fetch deleted objects.
        await repo.update_campaign(
            campaign_id,
            {
                "is_active": False,
                "image_s3_key": None,
                "image_thumb_s3_key": None,
                "brand_logo_s3_key": None,
            },
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

    decoded = _decode_image(content)
    if min(decoded.size) < MIN_SOURCE_DIMENSION:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Image too small. Minimum {MIN_SOURCE_DIMENSION}px on the short edge; "
                f"got {decoded.size[0]}x{decoded.size[1]}."
            ),
        )
    hero_bytes = _make_hero(decoded)
    thumb_bytes = _make_thumb(decoded)

    # Replace any existing variants under the campaign id.
    if campaign.image_s3_key:
        storage.delete(campaign.image_s3_key)
    if campaign.image_thumb_s3_key:
        storage.delete(campaign.image_thumb_s3_key)

    hero_key = storage.upload_campaign_image(campaign_id, hero_bytes, "jpg", variant="hero")
    thumb_key = storage.upload_campaign_image(campaign_id, thumb_bytes, "jpg", variant="thumb")
    campaign = await repo.update_campaign(
        campaign_id,
        {"image_s3_key": hero_key, "image_thumb_s3_key": thumb_key},
    )
    return await _build_admin_response(campaign, repo)


@router.post(
    "/admin/campaigns/{campaign_id}/brand-logo",
    response_model=AdminCampaignResponse,
)
async def admin_upload_campaign_brand_logo(
    campaign_id: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
):
    """Upload (or replace) the brand logo for a campaign. Single variant,
    aspect preserved, max 512px on the long edge. Always stored as opaque
    JPEG with a pure-white surround so the logo composites flush on the iOS
    card's white disc — see `_make_brand_logo` for the normalization pipeline."""
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

    decoded = _decode_image_keep_alpha(content)
    logo_bytes, ext = _make_brand_logo(decoded)

    if campaign.brand_logo_s3_key:
        storage.delete(campaign.brand_logo_s3_key)

    logo_key = storage.upload_brand_logo(campaign_id, logo_bytes, ext)
    campaign = await repo.update_campaign(
        campaign_id,
        {"brand_logo_s3_key": logo_key},
    )
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
    return _line_item_to_response(item)


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
    return [_line_item_to_response(i) for i in items]


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
    return _line_item_to_response(item)


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
    stats["pending_reviews"] = await repo.count_pending()
    return AdminStatsResponse(**stats)


# ---------------------------------------------------------------------------
# Admin: pending-review queue
# ---------------------------------------------------------------------------


@router.get(
    "/admin/pending-matches",
    response_model=list[BrandCashbackPendingMatchResponse],
)
async def admin_list_pending_matches(
    status: str = Query("pending", pattern="^(pending|approved|denied|all)$"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
):
    """Lists pending review rows. `status=all` returns every row regardless of state."""
    _require_admin(current_user)
    repo = BrandCashbackRepository(db)
    rows = await repo.get_pending_matches_for_admin(status)
    return [_pending_to_response(p, include_admin_context=True) for p in rows]


@router.post(
    "/admin/pending-matches/{pending_id}/approve",
    response_model=BrandCashbackPendingMatchResponse,
)
async def admin_approve_pending_match(
    pending_id: str,
    payload: AdminApprovePendingRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
):
    """Approve → create earning, credit points, optionally extend alt_line_items."""
    _require_admin(current_user)
    svc = BrandCashbackService(db)
    earning, error = await svc.approve_pending_match(
        pending_id, current_user.id, payload.add_to_alts
    )
    if error == APPROVE_NOT_FOUND:
        raise HTTPException(status_code=404, detail="Pending review not found")
    if error == APPROVE_ALREADY_REVIEWED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This review has already been processed",
        )
    if error == APPROVE_CAMPAIGN_FULL:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Campaign cap reached during review — auto-denied",
        )
    if error == APPROVE_USER_LIMIT:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="User per-campaign limit reached during review — auto-denied",
        )
    if error == APPROVE_CAMPAIGN_INACTIVE:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Campaign was deactivated since the review was queued — auto-denied",
        )
    if error == APPROVE_CAMPAIGN_EXPIRED:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Campaign expired since the review was queued — auto-denied",
        )
    if error == APPROVE_RECEIPT_OUTSIDE:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Receipt date is outside the campaign window after admin edit — auto-denied",
        )
    if error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=error
        )

    # Re-fetch with admin context for consistent response shape.
    repo = BrandCashbackRepository(db)
    refreshed = await repo.get_pending_match(pending_id)
    return _pending_to_response(refreshed, include_admin_context=True)


@router.post(
    "/admin/pending-matches/{pending_id}/deny",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def admin_deny_pending_match(
    pending_id: str,
    payload: AdminDenyPendingRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
):
    """Deny → marks as denied, surfaces reason to user for 7 days."""
    _require_admin(current_user)
    svc = BrandCashbackService(db)
    error = await svc.deny_pending_match(pending_id, current_user.id, payload.reason)
    if error == APPROVE_NOT_FOUND:
        raise HTTPException(status_code=404, detail="Pending review not found")
    if error == APPROVE_ALREADY_REVIEWED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This review has already been processed",
        )


# ---------------------------------------------------------------------------
# Admin: code-extension proposals (Tier 2 → product_codes review queue)
# ---------------------------------------------------------------------------


def _code_proposal_to_response(p) -> AdminCodeProposalResponse:
    """Map a BrandCashbackCodeProposal (with line_item + line_item.campaign
    eagerly loaded) to the admin response shape, flattening context fields."""
    li = p.line_item
    campaign = li.campaign if li else None
    return AdminCodeProposalResponse(
        id=p.id,
        line_item_id=p.line_item_id,
        code=p.code,
        proposed_at=p.proposed_at,
        status=p.status,
        campaign_id=campaign.id if campaign else None,
        campaign_brand_name=campaign.brand_name if campaign else None,
        campaign_product_name=campaign.product_name if campaign else None,
        line_item_store_name=li.store_name if li else None,
        line_item_exact_text=li.exact_line_item if li else None,
        source_user_id=p.source_user_id,
        source_receipt_id=p.source_receipt_id,
    )


@router.get(
    "/admin/code-proposals",
    response_model=list[AdminCodeProposalResponse],
)
async def admin_list_code_proposals(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
):
    """List pending code-extension proposals (admin-review queue for the
    Tier 2 auto-extend path that's now opt-in instead of automatic)."""
    _require_admin(current_user)
    repo = BrandCashbackRepository(db)
    rows = await repo.get_pending_code_proposals()
    return [_code_proposal_to_response(p) for p in rows]


@router.post(
    "/admin/code-proposals/{proposal_id}/approve",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def admin_approve_code_proposal(
    proposal_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
):
    """Approve → append the proposed code to the line item's product_codes."""
    _require_admin(current_user)
    svc = BrandCashbackService(db)
    error = await svc.approve_code_proposal(proposal_id, current_user.id)
    if error == APPROVE_NOT_FOUND:
        raise HTTPException(status_code=404, detail="Code proposal not found")
    if error == APPROVE_ALREADY_REVIEWED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This proposal has already been processed",
        )
    if error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=error
        )


@router.post(
    "/admin/code-proposals/{proposal_id}/reject",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def admin_reject_code_proposal(
    proposal_id: str,
    payload: AdminRejectCodeProposalRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
):
    """Reject → mark proposal rejected with a reason. Code NOT added."""
    _require_admin(current_user)
    svc = BrandCashbackService(db)
    error = await svc.reject_code_proposal(
        proposal_id, current_user.id, payload.reason
    )
    if error == APPROVE_NOT_FOUND:
        raise HTTPException(status_code=404, detail="Code proposal not found")
    if error == APPROVE_ALREADY_REVIEWED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This proposal has already been processed",
        )
    if error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=error
        )
