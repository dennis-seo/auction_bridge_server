"""개발/운영용 admin 엔드포인트. 1차에는 인증 없이 local 한정."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import get_auction_repository
from app.core.config import get_settings
from app.domain.auction.repository import AuctionRepository
from app.infrastructure.external.kakao_geocoder import KakaoGeocoder
from app.infrastructure.external.onbid_client import OnbidClient, OnbidTopCategory
from app.services.onbid_ingest_service import IngestStats, OnbidIngestService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


_TOP_CATEGORY_ALIASES: dict[str, str] = {
    "real_estate": OnbidTopCategory.REAL_ESTATE,
    "movable": OnbidTopCategory.MOVABLE,
    "rights": OnbidTopCategory.RIGHTS,
    "etc": OnbidTopCategory.ETC,
}


@router.post(
    "/sync/onbid",
    summary="온비드 데이터 수동 동기화 (개발용)",
)
async def sync_onbid(
    category: str | None = Query(
        default=None,
        description=(
            "상위 카테고리. 'real_estate'|'movable'|'rights'|'etc' "
            "또는 5자리 코드(10000/20000/...). 미지정 시 전체."
        ),
    ),
    pages: int = Query(default=1, ge=1, le=20),
    num_of_rows: int = Query(default=50, ge=1, le=500),
    repo: AuctionRepository = Depends(get_auction_repository),
) -> dict:
    settings = get_settings()
    if not settings.ONBID_SERVICE_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ONBID_SERVICE_KEY is not configured. data.go.kr 활용신청 후 .env에 설정하세요.",
        )

    ctgr_code: str | None
    if category is None:
        ctgr_code = None
    elif category in _TOP_CATEGORY_ALIASES:
        ctgr_code = _TOP_CATEGORY_ALIASES[category]
    elif category.isdigit() and len(category) == 5:
        ctgr_code = category
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"unknown category: {category}",
        )

    client = OnbidClient(service_key=settings.ONBID_SERVICE_KEY)
    geocoder = KakaoGeocoder(rest_api_key=settings.KAKAO_LOCAL_REST_API_KEY)
    service = OnbidIngestService(client=client, geocoder=geocoder, repo=repo)

    stats: IngestStats
    if ctgr_code is None:
        stats = await service.run_full(
            max_pages_per_category=pages, num_of_rows=num_of_rows,
        )
    else:
        stats = await service.run_one(
            ctgr_hirk_id=ctgr_code, max_pages=pages, num_of_rows=num_of_rows,
        )

    return {
        "category": category,
        "pages_per_category": pages,
        "num_of_rows": num_of_rows,
        "geocoder_enabled": geocoder.enabled,
        "stats": {
            "fetched": stats.fetched,
            "normalized": stats.normalized,
            "geocoded": stats.geocoded,
            "inserted": stats.inserted,
            "updated": stats.updated,
            "pages": stats.pages,
        },
    }
