"""APScheduler 기반 일 1회 새벽 배치.

FastAPI 워커가 여러 개일 경우 중복 실행 위험 — 1차에는 단일 워커 가정.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.api.deps import get_auction_repository
from app.core.config import get_settings
from app.infrastructure.external.kakao_geocoder import KakaoGeocoder
from app.infrastructure.external.onbid_client import OnbidClient
from app.services.onbid_ingest_service import OnbidIngestService

if TYPE_CHECKING:
    pass

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
    service = OnbidIngestService(client=client, geocoder=geocoder, repo=repo)

    logger.info("Daily Onbid ingest start.")
    stats = await service.run_full(max_pages_per_asset=20, num_of_rows=200)
    logger.info(
        "Daily Onbid ingest done — pages=%d fetched=%d normalized=%d "
        "geocoded=%d inserted=%d updated=%d",
        stats.pages, stats.fetched, stats.normalized,
        stats.geocoded, stats.inserted, stats.updated,
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
