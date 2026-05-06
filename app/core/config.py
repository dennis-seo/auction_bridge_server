from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # App
    APP_ENV: str = "local"
    APP_DEBUG: bool = True
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000
    USE_MOCK: bool = True

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/auctionbridge"

    # JWT
    JWT_SECRET: str = "change-me"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRES_MIN: int = 60
    JWT_REFRESH_TOKEN_EXPIRES_DAYS: int = 14

    # Kakao OAuth (Local API와 동일 키 공유)
    KAKAO_REST_API_KEY: str = ""
    KAKAO_REDIRECT_URI: str = ""
    KAKAO_CLIENT_SECRET: str = ""

    # Onbid
    ONBID_SERVICE_KEY: str = ""

    # CORS
    CORS_ORIGINS: str = "http://localhost:3000"

    # Scheduler
    SCHEDULER_ENABLED: bool = False
    SCHEDULER_HOUR_KST: int = 4   # 매일 04시 (KST)
    SCHEDULER_MINUTE_KST: int = 0

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
