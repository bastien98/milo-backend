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

    # Mistral
    MISTRAL_API_KEY: str = ""

    # Veryfi
    VERYFI_CLIENT_ID: str = ""
    VERYFI_CLIENT_SECRET: str = ""
    VERYFI_USERNAME: str = ""
    VERYFI_API_KEY: str = ""

    # File upload limits
    MAX_UPLOAD_SIZE_MB: int = 20
    ALLOWED_EXTENSIONS: set = {"pdf", "jpg", "jpeg", "png"}

    # Object Storage (Railway S3-compatible Bucket)
    # Railway auto-injects these AWS_* env vars when a bucket is attached
    AWS_S3_BUCKET_NAME: str = ""
    AWS_ENDPOINT_URL: str = ""
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    AWS_DEFAULT_REGION: str = "auto"

    # Fraud detection (PDF metadata, fingerprint dedup, receipt age)
    FRAUD_DETECTION_ENABLED: bool = True

    # Admin UIDs (Firebase UIDs) for brand cashback admin panel
    # Set via Railway env var: ADMIN_UIDS=uid1,uid2
    ADMIN_UIDS: List[str] = []

    # Firebase Web SDK config (public config, used by /admin HTML page)
    # Set via Railway env vars — copy from Firebase Console > Project Settings > Web app
    FIREBASE_WEB_API_KEY: Optional[str] = None
    FIREBASE_WEB_AUTH_DOMAIN: Optional[str] = None
    FIREBASE_WEB_PROJECT_ID: Optional[str] = None

    # CORS
    CORS_ORIGINS: List[str] = ["*"]

    # Database migrations
    USE_ALEMBIC: bool = True  # If True, skip create_all() in init_db() (Alembic handles migrations)

    # itsme OIDC
    ITSME_CLIENT_ID: str = ""
    ITSME_CLIENT_SECRET: str = ""
    ITSME_ENVIRONMENT: str = "e2e"  # "e2e" (sandbox) or "prd" (production)
    ITSME_REDIRECT_URI: str = ""  # e.g. https://scandalicious-api-production.up.railway.app/api/v2/auth/itsme/callback
    ITSME_SERVICE_CODE: str = ""  # Provided by itsme during onboarding

    @property
    def itsme_base_url(self) -> str:
        return f"https://idp.{self.ITSME_ENVIRONMENT}.itsme.services/v2"

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
