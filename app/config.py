from pydantic_settings import BaseSettings
from functools import lru_cache
from typing import Optional, List


class Settings(BaseSettings):
    # App
    APP_NAME: str = "Scandalicious Backend"
    DEBUG: bool = False
    API_V1_PREFIX: str = "/api/v1"

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://localhost:5432/scandalicious"
    DATABASE_POOL_SIZE: int = 5
    DATABASE_MAX_OVERFLOW: int = 10

    # Firebase
    FIREBASE_SERVICE_ACCOUNT: Optional[str] = None  # JSON string
    GOOGLE_APPLICATION_CREDENTIALS: Optional[str] = None  # File path

    # Anthropic
    ANTHROPIC_API_KEY: str = ""

    # File upload limits
    MAX_UPLOAD_SIZE_MB: int = 20
    ALLOWED_EXTENSIONS: set = {"pdf", "jpg", "jpeg", "png"}

    # CORS
    CORS_ORIGINS: List[str] = ["*"]

    class Config:
        env_file = ".env"
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    return Settings()
