import secrets
import logging

from fastapi import APIRouter, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends
from sqlalchemy.exc import IntegrityError

from app.api.deps import get_db
from app.db.repositories.user_repo import UserRepository
from app.db.repositories.user_profile_repo import UserProfileRepository
from app.schemas.itsme import (
    ItsmeAuthUrlResponse,
    ItsmeCallbackRequest,
    ItsmeAuthResponse,
    ItsmeUserInfoResponse,
)
from app.services.itsme_service import ItsmeService

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get(
    "/itsme/authorize",
    response_model=ItsmeAuthUrlResponse,
)
async def itsme_authorize():
    """
    Get the itsme authorization URL.

    The client should open this URL to start the itsme login flow.
    On mobile, this will trigger the itsme app via universal/app links.
    """
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    service = ItsmeService()
    authorization_url = service.get_authorization_url(state=state, nonce=nonce)

    return ItsmeAuthUrlResponse(
        authorization_url=authorization_url,
        state=state,
    )


@router.post(
    "/itsme/callback",
    response_model=ItsmeAuthResponse,
)
async def itsme_callback(
    request: ItsmeCallbackRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Exchange itsme authorization code for a Firebase custom token.

    The mobile app calls this after the user completes itsme authentication
    and receives the authorization code via the redirect URI.

    Returns a Firebase custom token that the client uses to sign in,
    along with verified user info from itsme.
    """
    service = ItsmeService()

    try:
        user_info, firebase_custom_token = await service.authenticate(request.code)
    except ValueError as e:
        logger.error(f"itsme authentication failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"itsme authentication failed: {str(e)}",
        )

    # Check if this is a new user (no DB record yet)
    firebase_uid = f"itsme:{user_info.sub}"
    user_repo = UserRepository(db)
    existing_user = await user_repo.get_by_firebase_uid(firebase_uid)
    is_new_user = existing_user is None

    if is_new_user:
        # Create the user record
        try:
            await user_repo.create(
                firebase_uid=firebase_uid,
                email=user_info.email,
                display_name=f"{user_info.given_name or ''} {user_info.family_name or ''}".strip() or None,
            )
        except IntegrityError:
            await db.rollback()
            is_new_user = False

    # Pre-populate profile with itsme verified data if new user
    if is_new_user and (user_info.given_name or user_info.family_name):
        profile_repo = UserProfileRepository(db)
        gender_map = {"male": "male", "female": "female"}
        itsme_gender = gender_map.get(user_info.gender) if user_info.gender else None

        await profile_repo.create(
            user_id=firebase_uid,
            first_name=user_info.given_name,
            last_name=user_info.family_name,
            gender=itsme_gender,
            # Geo data from itsme verified address
            street_address=user_info.street_address,
            postal_code=user_info.postal_code,
            city=user_info.locality,
            country=user_info.country,
        )

    await db.commit()

    return ItsmeAuthResponse(
        firebase_custom_token=firebase_custom_token,
        is_new_user=is_new_user,
        user_info=ItsmeUserInfoResponse(
            given_name=user_info.given_name,
            family_name=user_info.family_name,
            email=user_info.email,
            gender=user_info.gender,
            birthdate=user_info.birthdate,
            phone_number=user_info.phone_number,
            street_address=user_info.street_address,
            postal_code=user_info.postal_code,
            locality=user_info.locality,
            country=user_info.country,
        ),
    )
