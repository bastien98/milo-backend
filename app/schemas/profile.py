from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from app.models.enums import Gender, Language


class ProfileBase(BaseModel):
    """Base profile schema with common fields"""

    first_name: Optional[str] = Field(None, max_length=100)
    last_name: Optional[str] = Field(None, max_length=100)
    nickname: Optional[str] = Field(None, max_length=100)
    gender: Optional[Gender] = None
    age: Optional[int] = Field(None, ge=1, le=150)
    language: Optional[Language] = None
    preferred_stores: Optional[List[str]] = None


class ProfileCreate(ProfileBase):
    """Schema for creating or updating a complete profile"""

    pass


class ProfileUpdate(BaseModel):
    """Schema for partial profile updates"""

    first_name: Optional[str] = Field(None, max_length=100)
    last_name: Optional[str] = Field(None, max_length=100)
    nickname: Optional[str] = Field(None, max_length=100)
    gender: Optional[Gender] = None
    age: Optional[int] = Field(None, ge=1, le=150)
    language: Optional[Language] = None
    preferred_stores: Optional[List[str]] = None


class ProfileResponse(ProfileBase):
    """Schema for profile responses"""

    user_id: str
    profile_completed: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ProfileNotFoundResponse(BaseModel):
    """Schema for profile not found response"""

    error: str = "Profile not found"
    profile_completed: bool = False
