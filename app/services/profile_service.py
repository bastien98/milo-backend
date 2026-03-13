from typing import List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.user_profile_repo import UserProfileRepository
from app.models.user_profile import UserProfile
from app.models.enums import Gender, Language
from app.core.exceptions import ResourceNotFoundError


class ProfileService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.profile_repo = UserProfileRepository(db)

    async def get_profile(self, user_id: str) -> Optional[UserProfile]:
        """Get user profile by user_id (firebase_uid)."""
        return await self.profile_repo.get_by_user_id(user_id)

    async def create_or_update_profile(
        self,
        user_id: str,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        nickname: Optional[str] = None,
        gender: Optional[Gender] = None,
        age: Optional[int] = None,
        household_number: Optional[int] = None,
        language: Optional[Language] = None,
        preferred_stores: Optional[List[str]] = None,
        instagram_handle: Optional[str] = None,
    ) -> UserProfile:
        """Create or update user profile (POST operation)."""
        existing_profile = await self.profile_repo.get_by_user_id(user_id)

        if existing_profile:
            return await self.profile_repo.update(
                profile=existing_profile,
                first_name=first_name,
                last_name=last_name,
                nickname=nickname,
                gender=gender,
                age=age,
                household_number=household_number,
                language=language,
                preferred_stores=preferred_stores,
                instagram_handle=instagram_handle,
            )
        else:
            return await self.profile_repo.create(
                user_id=user_id,
                first_name=first_name,
                last_name=last_name,
                nickname=nickname,
                gender=gender,
                age=age,
                household_number=household_number,
                language=language,
                preferred_stores=preferred_stores,
            )

    async def update_profile(
        self,
        user_id: str,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        nickname: Optional[str] = None,
        gender: Optional[Gender] = None,
        age: Optional[int] = None,
        household_number: Optional[int] = None,
        language: Optional[Language] = None,
        preferred_stores: Optional[List[str]] = None,
        instagram_handle: Optional[str] = None,
    ) -> UserProfile:
        """Update existing user profile (PUT operation)."""
        existing_profile = await self.profile_repo.get_by_user_id(user_id)

        if not existing_profile:
            raise ResourceNotFoundError(
                message="Profile not found. Use POST to create a profile first.",
                resource_type="profile",
                resource_id=user_id,
            )

        return await self.profile_repo.update(
            profile=existing_profile,
            first_name=first_name,
            last_name=last_name,
            nickname=nickname,
            gender=gender,
            age=age,
            household_number=household_number,
            language=language,
            preferred_stores=preferred_stores,
            instagram_handle=instagram_handle,
        )

    async def delete_profile(self, user_id: str) -> None:
        """Delete user profile."""
        existing_profile = await self.profile_repo.get_by_user_id(user_id)

        if not existing_profile:
            raise ResourceNotFoundError(
                message="Profile not found",
                resource_type="profile",
                resource_id=user_id,
            )

        await self.profile_repo.delete(existing_profile)
