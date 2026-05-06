"""개발/운영용 admin 엔드포인트. 1차에는 인증 없이 local 한정."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import get_auction_repository
from app.core.config import get_settings
from app.domain.auction.repository import AuctionRepository
from app.domain.auction.schemas import AssetType
from app.infrastructure.external.kakao_geocoder import KakaoGeocoder
from app.infrastructure.external.onbid_client import OnbidAssetService, OnbidClient
from app.services.onbid_ingest_service import IngestStats, OnbidIngestService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


_ASSET_ALIASES: dict[str, OnbidAssetService] = {
    "realty": OnbidAssetService.REALTY,
    "real_estate": OnbidAssetService.REALTY,
    "movable": OnbidAssetService.MOVABLE,
    "vehicle": OnbidAssetService.VEHICLE,
    "car": OnbidAssetService.VEHICLE,
}


@router.post(
    "/sync/onbid",
    summary="온비드 데이터 수동 동기화 (개발용)",
)
async def sync_onbid(
    asset: str | None = Query(
        default=None,
        description="자산타입. 'realty'|'movable'|'vehicle'. 미지정 시 전체.",
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

    asset_svc: OnbidAssetService | None = None
    if asset is not None:
        key = asset.strip().lower()
        if key not in _ASSET_ALIASES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"unknown asset: {asset} (allowed: realty, movable, vehicle)",
            )
        asset_svc = _ASSET_ALIASES[key]

    client = OnbidClient(service_key=settings.ONBID_SERVICE_KEY)
    geocoder = KakaoGeocoder(rest_api_key=settings.KAKAO_REST_API_KEY)
    service = OnbidIngestService(
        client=client, geocoder=geocoder, repo=repo,
        geocode_concurrency=settings.GEOCODE_CONCURRENCY,
    )

    stats: IngestStats
    if asset_svc is None:
        stats = await service.run_full(
            max_pages_per_asset=pages, num_of_rows=num_of_rows,
        )
    else:
        stats = await service.run_one(
            asset=asset_svc, max_pages=pages, num_of_rows=num_of_rows,
        )

    return {
        "asset": asset,
        "pages_per_asset": pages,
        "num_of_rows": num_of_rows,
        "geocoder_enabled": geocoder.enabled,
        "stats": {
            "fetched": stats.fetched,
            "normalized": stats.normalized,
            "geocoded": stats.geocoded,
            "inserted": stats.inserted,
            "updated": stats.updated,
            "pages": stats.pages,
            "by_asset": stats.by_asset,
        },
    }


@router.post(
    "/enrich/realty-images",
    summary="부동산 상세 API로 image_urls 보강 (일일 쿼터 주의)",
)
async def enrich_realty_images(
    limit: int = Query(default=50, ge=1, le=500),
    repo: AuctionRepository = Depends(get_auction_repository),
) -> dict:
    settings = get_settings()
    if not settings.ONBID_SERVICE_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ONBID_SERVICE_KEY is not configured.",
        )

    client = OnbidClient(service_key=settings.ONBID_SERVICE_KEY)
    geocoder = KakaoGeocoder(rest_api_key=settings.KAKAO_REST_API_KEY)
    service = OnbidIngestService(
        client=client, geocoder=geocoder, repo=repo,
        geocode_concurrency=settings.GEOCODE_CONCURRENCY,
    )
    stats = await service.enrich_realty_image_urls(limit=limit)
    return {
        "limit": limit,
        "targeted": stats.targeted,
        "api_calls": stats.api_calls,
        "enriched": stats.enriched,
        "failed": stats.failed,
    }


@router.post(
    "/enrich/bid-results",
    summary="만료된 ongoing 매물의 입찰결과를 보강 (status: SOLD/FAILED/CANCELLED 확정)",
)
async def enrich_bid_results(
    limit: int = Query(default=50, ge=1, le=500),
    repo: AuctionRepository = Depends(get_auction_repository),
) -> dict:
    settings = get_settings()
    if not settings.ONBID_SERVICE_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ONBID_SERVICE_KEY is not configured.",
        )
    client = OnbidClient(service_key=settings.ONBID_SERVICE_KEY)
    geocoder = KakaoGeocoder(rest_api_key=settings.KAKAO_REST_API_KEY)
    service = OnbidIngestService(
        client=client, geocoder=geocoder, repo=repo,
        geocode_concurrency=settings.GEOCODE_CONCURRENCY,
    )
    stats = await service.enrich_bid_results(limit=limit)
    return {
        "limit": limit,
        "targeted": stats.targeted,
        "api_calls": stats.api_calls,
        "enriched": stats.enriched,
        "failed": stats.failed,
    }
