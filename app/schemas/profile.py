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
    household_number: Optional[int] = Field(None, ge=1, le=99)
    language: Optional[Language] = None
    preferred_stores: Optional[List[str]] = None
    instagram_handle: Optional[str] = Field(None, max_length=30)


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
    household_number: Optional[int] = Field(None, ge=1, le=99)
    language: Optional[Language] = None
    preferred_stores: Optional[List[str]] = None
    instagram_handle: Optional[str] = Field(None, max_length=30)


class ProfileResponse(ProfileBase):
    """Schema for profile responses"""
    user_id: str
    profile_completed: bool
    street_address: Optional[str] = None
    postal_code: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    instagram_handle: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ProfileNotFoundResponse(BaseModel):
    """Schema for profile not found response"""
    error: str = "Profile not found"
    profile_completed: bool = False
