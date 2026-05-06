"""APScheduler 기반 일 1회 새벽 배치.

FastAPI 워커가 여러 개일 경우 중복 실행 위험 — 1차에는 단일 워커 가정.
일 쿼터 1000/서비스를 고려해 다음 순서로:
  1) 신규 ingest (realty/movable/vehicle 목록)
  2) 만료된 ongoing 매물 입찰결과 보강 (status SOLD/FAILED 확정)
  3) (옵션) 부동산 사진 URL 보강
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.api.deps import get_auction_repository
from app.core.config import get_settings
from app.infrastructure.external.kakao_geocoder import KakaoGeocoder
from app.infrastructure.external.onbid_client import OnbidClient
from app.services.onbid_ingest_service import OnbidIngestService

logger = logging.getLogger(__name__)


_KST_TZ = "Asia/Seoul"


async def _run_daily_onbid_ingest() -> None:
    settings = get_settings()
    if not settings.ONBID_SERVICE_KEY:
        logger.warning("Skipping daily ingest — ONBID_SERVICE_KEY not configured.")
        return

    repo = get_auction_repository()
    client = OnbidClient(service_key=settings.ONBID_SERVICE_KEY)
    geocoder = KakaoGeocoder(rest_api_key=settings.KAKAO_REST_API_KEY)
    service = OnbidIngestService(
        client=client, geocoder=geocoder, repo=repo,
        geocode_concurrency=settings.GEOCODE_CONCURRENCY,
    )

    # 1) 목록 ingest
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

    # 2) 입찰결과 보강 — 만료된 ongoing 매물의 status 확정
    if settings.SCHEDULER_BID_RESULT_LIMIT > 0:
        logger.info("Bid-result enrich start (limit=%d).", settings.SCHEDULER_BID_RESULT_LIMIT)
        br = await service.enrich_bid_results(limit=settings.SCHEDULER_BID_RESULT_LIMIT)
        logger.info(
            "Bid-result enrich done — targeted=%d enriched=%d failed=%d",
            br.targeted, br.enriched, br.failed,
        )

    # 3) 이미지 보강 (선택) — 일일 쿼터를 많이 쓰므로 기본 0
    if settings.SCHEDULER_IMAGE_LIMIT > 0:
        logger.info("Image enrich start (limit=%d).", settings.SCHEDULER_IMAGE_LIMIT)
        img = await service.enrich_realty_image_urls(limit=settings.SCHEDULER_IMAGE_LIMIT)
        logger.info(
            "Image enrich done — targeted=%d enriched=%d failed=%d",
            img.targeted, img.enriched, img.failed,
        )


def build_scheduler() -> AsyncIOScheduler | None:
    """SCHEDULER_ENABLED=false면 None을 반환 — 호출부에서 lifespan 분기."""
    settings = get_settings()
    if not settings.SCHEDULER_ENABLED:
        return None

    sched = AsyncIOScheduler(timezone=_KST_TZ)
    sched.add_job(
        _run_daily_onbid_ingest,
        trigger=CronTrigger(
            hour=settings.SCHEDULER_HOUR_KST,
            minute=settings.SCHEDULER_MINUTE_KST,
            timezone=_KST_TZ,
        ),
        id="daily_onbid_ingest",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    return sched
