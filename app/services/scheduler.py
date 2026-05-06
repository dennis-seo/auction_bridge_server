"""일 1회 새벽 배치 작업 정의.

Cloud Run + Cloud Scheduler 조합에서는 외부 cron이 트리거하므로
이 모듈은 작업 함수만 노출한다. (in-process 스케줄러 제거)

일 쿼터 1000/서비스를 고려해 다음 순서로:
  1) 신규 ingest (realty/movable/vehicle 목록)
  2) 만료된 ongoing 매물 입찰결과 보강 (status SOLD/FAILED 확정)
  3) (옵션) 부동산 사진 URL 보강
"""
from __future__ import annotations

import logging

from app.api.deps import get_auction_repository
from app.core.config import get_settings
from app.infrastructure.external.kakao_geocoder import KakaoGeocoder
from app.infrastructure.external.onbid_client import OnbidClient
from app.services.onbid_ingest_service import OnbidIngestService

logger = logging.getLogger(__name__)


async def run_daily_onbid_ingest() -> dict:
    settings = get_settings()
    if not settings.ONBID_SERVICE_KEY:
        logger.warning("Skipping daily ingest — ONBID_SERVICE_KEY not configured.")
        return {"skipped": True, "reason": "ONBID_SERVICE_KEY not configured"}

    repo = get_auction_repository()
    client = OnbidClient(service_key=settings.ONBID_SERVICE_KEY)
    geocoder = KakaoGeocoder(rest_api_key=settings.KAKAO_REST_API_KEY)
    service = OnbidIngestService(
        client=client, geocoder=geocoder, repo=repo,
        geocode_concurrency=settings.GEOCODE_CONCURRENCY,
    )

    result: dict = {}

    logger.info("Daily Onbid ingest start.")
    stats = await service.run_full(
        max_pages_per_asset=settings.SCHEDULER_PAGES_PER_ASSET,
        num_of_rows=settings.SCHEDULER_NUM_OF_ROWS,
    )
    logger.info(
        "Daily Onbid ingest done — pages=%d fetched=%d normalized=%d "
        "geocoded=%d inserted=%d updated=%d",
        stats.pages, stats.fetched, stats.normalized,
        stats.geocoded, stats.inserted, stats.updated,
    )
    result["ingest"] = {
        "pages": stats.pages, "fetched": stats.fetched,
        "normalized": stats.normalized, "geocoded": stats.geocoded,
        "inserted": stats.inserted, "updated": stats.updated,
    }

    if settings.SCHEDULER_BID_RESULT_LIMIT > 0:
        logger.info("Bid-result enrich start (limit=%d).", settings.SCHEDULER_BID_RESULT_LIMIT)
        br = await service.enrich_bid_results(limit=settings.SCHEDULER_BID_RESULT_LIMIT)
        logger.info(
            "Bid-result enrich done — targeted=%d enriched=%d failed=%d",
            br.targeted, br.enriched, br.failed,
        )
        result["bid_result"] = {
            "targeted": br.targeted, "enriched": br.enriched, "failed": br.failed,
        }

    if settings.SCHEDULER_IMAGE_LIMIT > 0:
        logger.info("Image enrich start (limit=%d).", settings.SCHEDULER_IMAGE_LIMIT)
        img = await service.enrich_realty_image_urls(limit=settings.SCHEDULER_IMAGE_LIMIT)
        logger.info(
            "Image enrich done — targeted=%d enriched=%d failed=%d",
            img.targeted, img.enriched, img.failed,
        )
        result["image_enrich"] = {
            "targeted": img.targeted, "enriched": img.enriched, "failed": img.failed,
        }

    return result
