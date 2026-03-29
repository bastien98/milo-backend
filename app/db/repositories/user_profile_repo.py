from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user_profile import UserProfile
from app.models.enums import Gender, Language


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
        nickname: Optional[str] = None,
        gender: Optional[Gender] = None,
        age: Optional[int] = None,
        household_number: Optional[int] = None,
        language: Optional[Language] = None,
        preferred_stores: Optional[List[str]] = None,
        street_address: Optional[str] = None,
        postal_code: Optional[str] = None,
        city: Optional[str] = None,
        country: Optional[str] = None,
        itsme_sub: Optional[str] = None,
    ) -> UserProfile:
        """Create a new user profile."""
        # Determine if profile is completed (new fields: nickname, gender, age, language)
        profile_completed = all([nickname, gender, age is not None, language])

        profile = UserProfile(
            user_id=user_id,
            first_name=first_name,
            last_name=last_name,
            nickname=nickname,
            gender=gender,
            age=age,
            household_number=household_number,
            language=language,
            preferred_stores=preferred_stores,
            street_address=street_address,
            postal_code=postal_code,
            city=city,
            country=country,
            itsme_sub=itsme_sub,
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
        nickname: Optional[str] = None,
        gender: Optional[Gender] = None,
        age: Optional[int] = None,
        household_number: Optional[int] = None,
        language: Optional[Language] = None,
        preferred_stores: Optional[List[str]] = None,
        instagram_handle: Optional[str] = None,
    ) -> UserProfile:
        """Update an existing user profile."""
        # Update only provided fields
        if first_name is not None:
            profile.first_name = first_name
        if last_name is not None:
            profile.last_name = last_name
        if nickname is not None:
            profile.nickname = nickname
        if gender is not None:
            profile.gender = gender
        if age is not None:
            profile.age = age
        if household_number is not None:
            profile.household_number = household_number
        if language is not None:
            profile.language = language
        if preferred_stores is not None:
            from app.core.stores import resolve_store_name
            profile.preferred_stores = [
                resolve_store_name(s) or s for s in preferred_stores
            ]
        if instagram_handle is not None:
            profile.instagram_handle = instagram_handle

        # Update profile_completed status (new fields)
        profile.profile_completed = all([
            profile.nickname,
            profile.gender,
            profile.age is not None,
            profile.language,
        ])

        await self.db.flush()
        await self.db.refresh(profile)
        return profile

    async def delete(self, profile: UserProfile) -> None:
        """Delete a user profile."""
        await self.db.delete(profile)
        await self.db.flush()
