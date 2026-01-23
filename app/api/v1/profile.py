from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_current_db_user
from app.models.user import User
from app.schemas.profile import (
    ProfileCreate,
    ProfileUpdate,
    ProfileResponse,
    ProfileNotFoundResponse,
)
from app.services.profile_service import ProfileService
from app.core.exceptions import ResourceNotFoundError

router = APIRouter()


@router.get(
    "",
    response_model=ProfileResponse,
    responses={
        404: {
            "model": ProfileNotFoundResponse,
            "description": "Profile not found",
        }
    },
)
async def get_profile(
    current_user: User = Depends(get_current_db_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get the authenticated user's profile.

    Returns:
    - 200: Profile found
    - 404: Profile not found
    - 401: Invalid or missing authentication token
    """
    service = ProfileService(db)
    profile = await service.get_profile(current_user.firebase_uid)

    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "Profile not found",
                "profile_completed": False,
            },
        )

    return profile


@router.post(
    "",
    response_model=ProfileResponse,
    status_code=status.HTTP_200_OK,
)
async def create_or_update_profile(
    profile_data: ProfileCreate,
    current_user: User = Depends(get_current_db_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Create or update the authenticated user's profile.

    Automatically sets profile_completed to true when all fields are provided.

    Returns:
    - 200: Profile created or updated successfully
    - 400: Invalid input data (e.g., invalid gender value)
    - 401: Invalid or missing authentication token
    """
    service = ProfileService(db)
    profile = await service.create_or_update_profile(
        user_id=current_user.firebase_uid,
        first_name=profile_data.first_name,
        last_name=profile_data.last_name,
        gender=profile_data.gender,
    )

    await db.commit()
    return profile


@router.put(
    "",
    response_model=ProfileResponse,
    responses={
        404: {
            "description": "Profile not found",
        }
    },
)
async def update_profile(
    profile_data: ProfileUpdate,
    current_user: User = Depends(get_current_db_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Update specific fields of the authenticated user's existing profile.

    Only updates the fields that are provided in the request.

    Returns:
    - 200: Profile updated successfully
    - 400: Invalid input data (e.g., invalid gender value)
    - 401: Invalid or missing authentication token
    - 404: Profile not found (use POST to create first)
    """
    service = ProfileService(db)

    try:
        profile = await service.update_profile(
            user_id=current_user.firebase_uid,
            first_name=profile_data.first_name,
            last_name=profile_data.last_name,
            gender=profile_data.gender,
        )
    except ResourceNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "not_found", "message": str(e)},
        )

    await db.commit()
    return profile
