import logging
import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.api.v1.router import api_v1_router
from app.core.config import get_settings

logger = logging.getLogger(__name__)


def _client_ip(request: Request) -> str:
    """Cloud Run은 실제 클라이언트 IP를 X-Forwarded-For 앞쪽에 넣는다."""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def create_app() -> FastAPI:
    settings = get_settings()

    # non-local 환경에서 시크릿이 기본값/예시값이면 기동 실패(fail-fast) — 토큰 위조 방지.
    if settings.APP_ENV != "local" and settings.JWT_SECRET.startswith("change-me"):
        raise RuntimeError(
            "JWT_SECRET must be overridden with a real random value in non-local "
            "environments (예: openssl rand -hex 32)."
        )

    app = FastAPI(
        title="AuctionBridge API",
        description="대한민국 법원 경매 / 캠코 온비드 통합 API",
        version="0.1.0",
        # 프로덕션에서는 API 스키마/문서를 비공개로.
        docs_url="/docs" if settings.APP_ENV == "local" else None,
        redoc_url="/redoc" if settings.APP_ENV == "local" else None,
        openapi_url="/openapi.json" if settings.APP_ENV == "local" else None,
    )

    limiter = Limiter(
        key_func=_client_ip,
        default_limits=[settings.RATE_LIMIT_DEFAULT] if settings.RATE_LIMIT_ENABLED else [],
        enabled=settings.RATE_LIMIT_ENABLED,
    )
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        # Vercel preview 같은 hash 기반 동적 origin 매칭. 비어있으면 None 으로 패스.
        allow_origin_regex=settings.CORS_ORIGIN_REGEX or None,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_v1_router, prefix="/api/v1")

    @app.get("/health", tags=["meta"])
    async def health():
        return {"status": "ok", "env": settings.APP_ENV, "use_mock": settings.USE_MOCK}

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    port = int(os.environ.get("PORT", settings.APP_PORT))
    uvicorn.run(
        "main:app",
        host=settings.APP_HOST,
        port=port,
        reload=settings.APP_DEBUG,
    )
