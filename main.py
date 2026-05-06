import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_v1_router
from app.core.config import get_settings

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="AuctionBridge API",
        description="대한민국 법원 경매 / 캠코 온비드 통합 API",
        version="0.1.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
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
