from typing import Optional

from pydantic import BaseModel


class ItsmeAuthUrlResponse(BaseModel):
    """Response containing the itsme authorization URL."""
    authorization_url: str
    state: str


class ItsmeCallbackRequest(BaseModel):
    """Request body when the mobile app sends the itsme authorization code."""
    code: str
    state: str


class ItsmeAuthResponse(BaseModel):
    """Response after successful itsme authentication."""
    firebase_custom_token: str
    is_new_user: bool
    user_info: "ItsmeUserInfoResponse"


class ItsmeUserInfoResponse(BaseModel):
    """Verified user data from itsme, returned to the client."""
    given_name: Optional[str] = None
    family_name: Optional[str] = None
    email: Optional[str] = None
    gender: Optional[str] = None
    birthdate: Optional[str] = None
    phone_number: Optional[str] = None
    # Address
    street_address: Optional[str] = None
    postal_code: Optional[str] = None
    locality: Optional[str] = None
    country: Optional[str] = None
