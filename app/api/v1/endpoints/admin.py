"""개발/운영용 admin 엔드포인트. 1차에는 인증 없이 local 한정."""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select, update

from app.api.deps import get_auction_repository
from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.domain.auction.repository import AuctionRepository
from app.domain.auction.schemas import AssetType
from app.infrastructure.db.models import AuctionORM
from app.infrastructure.external.kakao_geocoder import KakaoGeocoder
from app.infrastructure.external.onbid_client import OnbidAssetService, OnbidClient
from app.services.onbid_ingest_service import (
    IngestStats,
    OnbidIngestService,
    compose_address,
)

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
            "by_prpt_div": stats.by_prpt_div,
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


@router.post(
    "/enrich/bid-results-list",
    summary="#8 입찰결과목록으로 최근 개찰분 일괄 보강 (호출 수 절감)",
)
async def enrich_bid_results_by_list(
    days_lookback: int = Query(default=2, ge=1, le=14),
    num_of_rows: int = Query(default=100, ge=1, le=500),
    max_pages: int = Query(default=20, ge=1, le=50),
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
    stats = await service.enrich_bid_results_by_list(
        days_lookback=days_lookback,
        num_of_rows=num_of_rows,
        max_pages_per_combo=max_pages,
    )
    return {
        "days_lookback": days_lookback,
        "num_of_rows": num_of_rows,
        "max_pages_per_combo": max_pages,
        "targeted": stats.targeted,
        "api_calls": stats.api_calls,
        "enriched": stats.enriched,
        "failed": stats.failed,
    }


@router.post(
    "/enrich/movable-images",
    summary="동산 상세 API(#5)로 image_urls 보강",
)
async def enrich_movable_images(
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
    stats = await service.enrich_movable_image_urls(limit=limit)
    return {
        "limit": limit,
        "targeted": stats.targeted,
        "api_calls": stats.api_calls,
        "enriched": stats.enriched,
        "failed": stats.failed,
    }


@router.post(
    "/enrich/bid-info",
    summary="#7 물건상세 입찰정보로 auctions.bid_info 보강",
)
async def enrich_bid_info(
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
    stats = await service.enrich_bid_info(limit=limit)
    return {
        "limit": limit,
        "targeted": stats.targeted,
        "api_calls": stats.api_calls,
        "enriched": stats.enriched,
        "failed": stats.failed,
    }


@router.post(
    "/enrich/pbanc-resolve",
    summary="D안 Phase A — pbanc_mng_no 매핑 해결 (#15 getPbancList2)",
)
async def enrich_pbanc_resolve(
    limit: int = Query(default=200, ge=1, le=2000),
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
    stats = await service.enrich_pbanc_mng_no(limit=limit)
    return {
        "limit": limit,
        "targeted": stats.targeted,
        "resolved": stats.enriched,
        "failed": stats.failed,
        "api_calls": stats.api_calls,
    }


@router.post(
    "/enrich/missing-rounds",
    summary="D안 Phase B — 공고 단위 누락 회차 보강 (#18 getPbancCltrInf2)",
)
async def enrich_missing_rounds(
    limit: int = Query(default=100, ge=1, le=1000),
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
    stats = await service.enrich_missing_rounds_via_pbanc(limit=limit)
    return {
        "limit": limit,
        "targeted": stats.targeted,
        "enriched": stats.enriched,
        "failed": stats.failed,
        "api_calls": stats.api_calls,
    }


# =====================================================================
# 좌표 백필 — 동(洞) centroid에 뭉친 row를 parcel 단위로 재지오코딩
# =====================================================================
async def _backfill_geocoding_run(
    *, dry_run: bool, limit: int, min_cluster: int, concurrency: int,
) -> dict:
    """동일 location N>=min_cluster 누적 row를 limit건 재지오코딩.

    ingest 와 동일한 compose_address(region_*, title=title) 로 입력 강화 후
    KakaoGeocoder.lookup — parcel-level 응답만 채택. 좌표 못 구하면
    location=NULL 로 정정(가짜 좌표 잔존 방지).
    """
    settings = get_settings()
    if not settings.KAKAO_REST_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="KAKAO_REST_API_KEY is not configured.",
        )
    geocoder = KakaoGeocoder(rest_api_key=settings.KAKAO_REST_API_KEY)

    # 1) 동일 location N>=min_cluster 누적 row 추출
    async with AsyncSessionLocal() as session:
        dup_loc_subq = (
            select(AuctionORM.location)
            .where(AuctionORM.location.is_not(None))
            .group_by(AuctionORM.location)
            .having(func.count() >= min_cluster)
            .subquery()
        )
        rows = (await session.execute(
            select(
                AuctionORM.id,
                AuctionORM.title,
                AuctionORM.address,
                AuctionORM.region_sido,
                AuctionORM.region_sigungu,
                AuctionORM.region_emd,
            )
            .where(AuctionORM.location.in_(select(dup_loc_subq.c.location)))
            .order_by(AuctionORM.id)
            .limit(limit)
        )).all()

    stats = {
        "targeted": len(rows),
        "api_calls": 0,
        "updated": 0,
        "nullified": 0,
        "skipped_no_address": 0,
        "failed": 0,
    }
    samples: list[dict] = []
    if not rows:
        return {"dry_run": dry_run, "stats": stats, "samples": samples}

    sem = asyncio.Semaphore(concurrency)

    async def _one(row) -> None:
        new_addr = compose_address(
            row.region_sido, row.region_sigungu, row.region_emd, title=row.title,
        )
        if not new_addr:
            stats["skipped_no_address"] += 1
            return
        async with sem:
            stats["api_calls"] += 1
            lng, lat = await geocoder.lookup(new_addr)
        if len(samples) < 20:
            samples.append({
                "id": row.id,
                "old_address": row.address,
                "new_address": new_addr,
                "lng": lng, "lat": lat,
            })
        if dry_run:
            return
        try:
            async with AsyncSessionLocal() as session:
                values: dict = {"address": new_addr}
                if lng is not None and lat is not None:
                    values["location"] = func.ST_SetSRID(
                        func.ST_MakePoint(lng, lat), 4326,
                    )
                else:
                    values["location"] = None
                await session.execute(
                    update(AuctionORM)
                    .where(AuctionORM.id == row.id)
                    .values(**values)
                )
                await session.commit()
        except Exception as e:  # noqa: BLE001
            logger.warning("backfill update failed id=%d: %s", row.id, e)
            stats["failed"] += 1
            return
        if lng is None or lat is None:
            stats["nullified"] += 1
        else:
            stats["updated"] += 1

    await asyncio.gather(*[_one(r) for r in rows])
    return {"dry_run": dry_run, "stats": stats, "samples": samples}


@router.post(
    "/backfill/geocoding",
    summary="동 centroid에 뭉친 매물 좌표를 parcel 단위로 재지오코딩",
)
async def backfill_geocoding(
    dry_run: bool = Query(default=True, description="true면 DB 변경 없이 결과만 반환."),
    limit: int = Query(default=200, ge=1, le=5000),
    min_cluster: int = Query(default=2, ge=2, le=500,
                              description="이 수 이상 누적된 location만 대상."),
    concurrency: int = Query(default=10, ge=1, le=30),
) -> dict:
    return await _backfill_geocoding_run(
        dry_run=dry_run, limit=limit,
        min_cluster=min_cluster, concurrency=concurrency,
    )
