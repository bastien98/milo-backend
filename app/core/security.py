import json
from typing import Optional

import firebase_admin
from firebase_admin import auth, credentials
from fastapi import HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.config import get_settings

settings = get_settings()

# Initialize Firebase Admin SDK
_firebase_app = None


def init_firebase():
    """Initialize Firebase Admin SDK."""
    global _firebase_app
    if _firebase_app is None:
        # Option 1: Use service account file path
        if settings.GOOGLE_APPLICATION_CREDENTIALS:
            cred = credentials.Certificate(settings.GOOGLE_APPLICATION_CREDENTIALS)
        # Option 2: Use environment variable with JSON content
        elif settings.FIREBASE_SERVICE_ACCOUNT:
            service_account = json.loads(settings.FIREBASE_SERVICE_ACCOUNT)
            cred = credentials.Certificate(service_account)
        else:
            raise ValueError(
                "Firebase credentials not configured. "
                "Set FIREBASE_SERVICE_ACCOUNT or GOOGLE_APPLICATION_CREDENTIALS"
            )

        _firebase_app = firebase_admin.initialize_app(cred)
    return _firebase_app


# Initialize on module load
try:
    init_firebase()
except Exception:
    # Allow startup without Firebase for development/testing
    pass

security = HTTPBearer()


class FirebaseUser:
    """Represents an authenticated Firebase user."""

    def __init__(self, uid: str, email: Optional[str], name: Optional[str]):
        self.uid = uid
        self.email = email
        self.name = name


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Security(security),
) -> FirebaseUser:
    """
    Validate Firebase ID token and return user info.

    This is used as a FastAPI dependency for protected endpoints.
    """
    token = credentials.credentials

    try:
        # Verify the ID token
        decoded_token = auth.verify_id_token(token)

        return FirebaseUser(
            uid=decoded_token["uid"],
            email=decoded_token.get("email"),
            name=decoded_token.get("name"),
        )
    except auth.ExpiredIdTokenError:
        raise HTTPException(
            status_code=401,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except auth.InvalidIdTokenError:
        raise HTTPException(
            status_code=401,
            detail="Invalid authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except Exception as e:
        raise HTTPException(
            status_code=401,
            detail=f"Authentication failed: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )
