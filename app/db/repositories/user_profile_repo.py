from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user_profile import UserProfile
from app.models.enums import Gender


class UserProfileRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_user_id(self, user_id: str) -> Optional[UserProfile]:
        """Get user profile by user_id (firebase_uid)."""
        result = await self.db.execute(
            select(UserProfile).where(UserProfile.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        user_id: str,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        gender: Optional[Gender] = None,
    ) -> UserProfile:
        """Create a new user profile."""
        # Determine if profile is completed
        profile_completed = all([first_name, last_name, gender])

        profile = UserProfile(
            user_id=user_id,
            first_name=first_name,
            last_name=last_name,
            gender=gender,
            profile_completed=profile_completed,
        )
        self.db.add(profile)
        await self.db.flush()
        await self.db.refresh(profile)
        return profile

    async def update(
        self,
        profile: UserProfile,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        gender: Optional[Gender] = None,
    ) -> UserProfile:
        """Update an existing user profile."""
        # Update only provided fields
        if first_name is not None:
            profile.first_name = first_name
        if last_name is not None:
            profile.last_name = last_name
        if gender is not None:
            profile.gender = gender

        # Update profile_completed status
        profile.profile_completed = all([
            profile.first_name,
            profile.last_name,
            profile.gender,
        ])

        await self.db.flush()
        await self.db.refresh(profile)
        return profile

    async def delete(self, profile: UserProfile) -> None:
        """Delete a user profile."""
        await self.db.delete(profile)
        await self.db.flush()
