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
    # 정확한 매칭이 필요한 origin 들 — 콤마 구분
    CORS_ORIGINS: str = "http://localhost:3000"
    # hash 기반 동적 origin (예: Vercel preview) 매칭용 정규식.
    # 비어있으면 무시. 예: r"^https://auction-bridge.*\.vercel\.app$"
    CORS_ORIGIN_REGEX: str = ""

    # Daily ingest 작업 파라미터 (외부 cron이 트리거)
    # prpt_div_cd별로 페이징하므로 (자산타입 × prpt_div_cd) 단위로 적용된다.
    # 일일 1000건/서비스 한도: 3 자산 × 7 카테고리 × 50 페이지 = 1050 (상한), 실제로는
    # has_more=false로 일찍 종료되는 카테고리가 많아 200~500건 수준.
    SCHEDULER_PAGES_PER_ASSET: int = 50      # 자산타입 × prpt_div_cd당 페이지 수
    SCHEDULER_NUM_OF_ROWS: int = 500         # 페이지당 행
    SCHEDULER_BID_RESULT_LIMIT: int = 200    # 입찰결과 보강 1회 한도
    SCHEDULER_IMAGE_LIMIT: int = 0           # 이미지 보강 1회 한도 (0=skip; quota 보존)

    # Cloud Scheduler → Cloud Run 인증 (OIDC)
    CRON_SERVICE_ACCOUNT_EMAIL: str = ""     # Cloud Scheduler가 사용하는 SA 이메일
    CRON_AUDIENCE: str = ""                  # 보통 Cloud Run 서비스 URL

    # 지오코딩 동시성
    GEOCODE_CONCURRENCY: int = 10

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
