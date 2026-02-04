from pydantic_settings import BaseSettings
from pydantic import field_validator
from functools import lru_cache
from typing import Optional, List


class Settings(BaseSettings):
    # App
    APP_NAME: str = "Scandalicious Backend"
    DEBUG: bool = False

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://localhost:5432/scandalicious"
    DATABASE_POOL_SIZE: int = 5
    DATABASE_MAX_OVERFLOW: int = 10

    # Firebase
    FIREBASE_SERVICE_ACCOUNT: Optional[str] = None  # JSON string
    GOOGLE_APPLICATION_CREDENTIALS: Optional[str] = None  # File path

    # Gemini
    GEMINI_API_KEY: str = ""

    # Veryfi
    VERYFI_CLIENT_ID: str = ""
    VERYFI_CLIENT_SECRET: str = ""
    VERYFI_USERNAME: str = ""
    VERYFI_API_KEY: str = ""

    # File upload limits
    MAX_UPLOAD_SIZE_MB: int = 20
    ALLOWED_EXTENSIONS: set = {"pdf", "jpg", "jpeg", "png"}

    # CORS
    CORS_ORIGINS: List[str] = ["*"]

    # EnableBanking (Open Banking)
    ENABLEBANKING_APP_ID: str = ""
    ENABLEBANKING_PRIVATE_KEY: Optional[str] = None  # PEM-encoded private key string
    ENABLEBANKING_PRIVATE_KEY_PATH: Optional[str] = None  # Path to private key file
    ENABLEBANKING_REDIRECT_URL: str = ""  # OAuth callback URL
    ENABLEBANKING_SANDBOX: bool = False  # Use sandbox API for testing

    # Callback redirects for banking
    FRONTEND_URL: str = "https://app.milo.com"  # Web app URL for redirects
    MOBILE_DEEP_LINK_SCHEME: str = "milo"  # Deep link scheme for mobile app

    # Database migrations
    USE_ALEMBIC: bool = True  # If True, skip create_all() in init_db() (Alembic handles migrations)

    # Apple Wallet Pass signing
    WALLET_PASS_TYPE_ID: str = "pass.com.deepmaind.milo"
    WALLET_TEAM_ID: str = ""
    WALLET_CERT_BASE64: Optional[str] = None  # Base64-encoded .p12 certificate
    WALLET_CERT_PASSWORD: str = ""
    WALLET_WWDR_CERT_BASE64: Optional[str] = None  # Base64-encoded WWDR .pem certificate

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def convert_database_url(cls, v: str) -> str:
        """Convert postgresql:// to postgresql+asyncpg:// for async support."""
        if v and v.startswith("postgresql://"):
            return v.replace("postgresql://", "postgresql+asyncpg://", 1)
        return v

    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "ignore"  # Allow extra env variables to be ignored


@lru_cache()
def get_settings() -> Settings:
    return Settings()
