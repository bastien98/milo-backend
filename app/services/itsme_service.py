import logging
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlencode

import httpx
from firebase_admin import auth as firebase_auth

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


@dataclass
class ItsmeUserInfo:
    """Verified user data returned by itsme."""
    sub: str  # Unique, persistent user identifier per partner
    given_name: Optional[str] = None
    family_name: Optional[str] = None
    email: Optional[str] = None
    email_verified: Optional[bool] = None
    gender: Optional[str] = None
    birthdate: Optional[str] = None
    phone_number: Optional[str] = None
    phone_number_verified: Optional[bool] = None
    # Address fields
    street_address: Optional[str] = None
    postal_code: Optional[str] = None
    locality: Optional[str] = None  # City
    country: Optional[str] = None


class ItsmeService:
    """Handles itsme OpenID Connect authentication flow."""

    def __init__(self):
        self.client_id = settings.ITSME_CLIENT_ID
        self.client_secret = settings.ITSME_CLIENT_SECRET
        self.redirect_uri = settings.ITSME_REDIRECT_URI
        self.service_code = settings.ITSME_SERVICE_CODE
        self.base_url = settings.itsme_base_url

    def get_authorization_url(self, state: str, nonce: str) -> str:
        """Build the itsme authorization URL to redirect the user to."""
        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": f"openid service:{self.service_code} profile email address phone",
            "state": state,
            "nonce": nonce,
        }
        return f"{self.base_url}/authorization?{urlencode(params)}"

    async def exchange_code_for_tokens(self, code: str) -> dict:
        """Exchange the authorization code for access and ID tokens."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/token",
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": self.redirect_uri,
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=30.0,
            )

            if response.status_code != 200:
                logger.error(f"itsme token exchange failed: {response.status_code} {response.text}")
                raise ValueError(f"itsme token exchange failed: {response.status_code}")

            return response.json()

    async def get_userinfo(self, access_token: str) -> ItsmeUserInfo:
        """Fetch verified user info from the itsme UserInfo endpoint."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/userinfo",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=30.0,
            )

            if response.status_code != 200:
                logger.error(f"itsme userinfo failed: {response.status_code} {response.text}")
                raise ValueError(f"itsme userinfo request failed: {response.status_code}")

            data = response.json()

        # Parse address if present
        address = data.get("address", {})

        return ItsmeUserInfo(
            sub=data["sub"],
            given_name=data.get("given_name"),
            family_name=data.get("family_name"),
            email=data.get("email"),
            email_verified=data.get("email_verified"),
            gender=data.get("gender"),
            birthdate=data.get("birthdate"),
            phone_number=data.get("phone_number"),
            phone_number_verified=data.get("phone_number_verified"),
            street_address=address.get("street_address"),
            postal_code=address.get("postal_code"),
            locality=address.get("locality"),
            country=address.get("country"),
        )

    async def authenticate(self, code: str) -> tuple[ItsmeUserInfo, str]:
        """
        Full itsme authentication flow:
        1. Exchange authorization code for tokens
        2. Fetch user info
        3. Create a Firebase custom token for the client

        Returns (user_info, firebase_custom_token).
        """
        # Step 1: Exchange code for tokens
        tokens = await self.exchange_code_for_tokens(code)
        access_token = tokens["access_token"]

        # Step 2: Fetch verified user data
        user_info = await self.get_userinfo(access_token)

        # Step 3: Create or update Firebase user and issue custom token
        # Use itsme sub as the Firebase UID (prefixed to avoid collisions)
        firebase_uid = f"itsme:{user_info.sub}"

        try:
            # Try to get existing Firebase user
            firebase_auth.get_user(firebase_uid)
        except firebase_auth.UserNotFoundError:
            # Create new Firebase user
            firebase_auth.create_user(
                uid=firebase_uid,
                email=user_info.email,
                display_name=f"{user_info.given_name or ''} {user_info.family_name or ''}".strip() or None,
            )

        # Generate custom token for the client to sign in with
        custom_token = firebase_auth.create_custom_token(firebase_uid)

        return user_info, custom_token.decode("utf-8") if isinstance(custom_token, bytes) else custom_token
