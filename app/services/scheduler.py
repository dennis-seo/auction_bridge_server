"""일 1회 새벽 배치 작업 정의.

Cloud Run + Cloud Scheduler 조합에서는 외부 cron이 트리거하므로
이 모듈은 작업 함수만 노출한다. (in-process 스케줄러 제거)

일 쿼터 1000/서비스를 고려해 다음 순서로:
  1) 신규 ingest (realty/movable/vehicle 목록)               — #1,#2,#3
  2) 입찰결과 일괄 보강 (#8 — 어제~오늘 개찰분, ongoing 매물과 매칭)
  3) 누락분 fallback 보강 (#9 — #8로 못 잡은 만료 매물만)
  4) 부동산 사진 보강 (#4)
  5) 동산   사진 보강 (#5)
  6) 입찰정보 보강 (#7 — 매물 상세 화면용 풍부도)
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

    # 1) 신규 ingest
    logger.info("Daily Onbid ingest start.")
    stats = await service.run_full(
        max_pages_per_asset=settings.SCHEDULER_PAGES_PER_ASSET,
        num_of_rows=settings.SCHEDULER_NUM_OF_ROWS,
    )
    logger.info(
        "Daily Onbid ingest done — pages=%d fetched=%d normalized=%d "
        "geocoded=%d inserted=%d updated=%d by_asset=%s by_prpt_div=%s",
        stats.pages, stats.fetched, stats.normalized,
        stats.geocoded, stats.inserted, stats.updated,
        stats.by_asset, stats.by_prpt_div,
    )
    result["ingest"] = {
        "pages": stats.pages, "fetched": stats.fetched,
        "normalized": stats.normalized, "geocoded": stats.geocoded,
        "inserted": stats.inserted, "updated": stats.updated,
        "by_asset": stats.by_asset,
        "by_prpt_div": stats.by_prpt_div,
    }

    # 1.5a) D안 Phase A — pbanc_mng_no 매핑 해결
    if settings.SCHEDULER_PBANC_RESOLVE_LIMIT > 0:
        logger.info(
            "Pbanc mapping resolve start (limit=%d).",
            settings.SCHEDULER_PBANC_RESOLVE_LIMIT,
        )
        pa = await service.enrich_pbanc_mng_no(
            limit=settings.SCHEDULER_PBANC_RESOLVE_LIMIT,
        )
        logger.info(
            "Pbanc mapping resolve done — targeted=%d resolved=%d failed=%d api_calls=%d",
            pa.targeted, pa.enriched, pa.failed, pa.api_calls,
        )
        result["pbanc_resolve"] = {
            "targeted": pa.targeted, "resolved": pa.enriched,
            "failed": pa.failed, "api_calls": pa.api_calls,
        }

    # 1.5b) D안 Phase B — 공고 단위 누락 회차 보강
    if settings.SCHEDULER_PBANC_ENRICH_LIMIT > 0:
        logger.info(
            "Missing rounds enrich start (limit=%d).",
            settings.SCHEDULER_PBANC_ENRICH_LIMIT,
        )
        pb = await service.enrich_missing_rounds_via_pbanc(
            limit=settings.SCHEDULER_PBANC_ENRICH_LIMIT,
        )
        logger.info(
            "Missing rounds enrich done — targeted=%d enriched=%d failed=%d api_calls=%d",
            pb.targeted, pb.enriched, pb.failed, pb.api_calls,
        )
        result["pbanc_enrich"] = {
            "targeted": pb.targeted, "enriched": pb.enriched,
            "failed": pb.failed, "api_calls": pb.api_calls,
        }

    # 2) #8 입찰결과목록 일괄 보강
    if settings.SCHEDULER_BID_RESULT_LIST_MAX_PAGES > 0:
        logger.info(
            "Bid-result list-enrich start (days=%d, max_pages=%d).",
            settings.SCHEDULER_BID_RESULT_LIST_DAYS,
            settings.SCHEDULER_BID_RESULT_LIST_MAX_PAGES,
        )
        br_list = await service.enrich_bid_results_by_list(
            days_lookback=settings.SCHEDULER_BID_RESULT_LIST_DAYS,
            max_pages_per_combo=settings.SCHEDULER_BID_RESULT_LIST_MAX_PAGES,
        )
        logger.info(
            "Bid-result list-enrich done — targeted=%d enriched=%d api_calls=%d",
            br_list.targeted, br_list.enriched, br_list.api_calls,
        )
        result["bid_result_list"] = {
            "targeted": br_list.targeted,
            "enriched": br_list.enriched,
            "api_calls": br_list.api_calls,
        }

    # 3) #9 fallback — #8로 못 잡은 만료 매물만
    if settings.SCHEDULER_BID_RESULT_LIMIT > 0:
        logger.info(
            "Bid-result detail-fallback start (limit=%d).",
            settings.SCHEDULER_BID_RESULT_LIMIT,
        )
        br = await service.enrich_bid_results(limit=settings.SCHEDULER_BID_RESULT_LIMIT)
        logger.info(
            "Bid-result detail-fallback done — targeted=%d enriched=%d failed=%d",
            br.targeted, br.enriched, br.failed,
        )
        result["bid_result_detail"] = {
            "targeted": br.targeted, "enriched": br.enriched, "failed": br.failed,
        }

    # 4) 부동산 사진 (#4)
    if settings.SCHEDULER_IMAGE_LIMIT > 0:
        logger.info(
            "Realty image enrich start (limit=%d).", settings.SCHEDULER_IMAGE_LIMIT,
        )
        img = await service.enrich_realty_image_urls(limit=settings.SCHEDULER_IMAGE_LIMIT)
        logger.info(
            "Realty image enrich done — targeted=%d enriched=%d failed=%d",
            img.targeted, img.enriched, img.failed,
        )
        result["image_enrich_realty"] = {
            "targeted": img.targeted, "enriched": img.enriched, "failed": img.failed,
        }

    # 5) 동산 사진 (#5)
    if settings.SCHEDULER_MOVABLE_IMAGE_LIMIT > 0:
        logger.info(
            "Movable image enrich start (limit=%d).",
            settings.SCHEDULER_MOVABLE_IMAGE_LIMIT,
        )
        img_m = await service.enrich_movable_image_urls(
            limit=settings.SCHEDULER_MOVABLE_IMAGE_LIMIT
        )
        logger.info(
            "Movable image enrich done — targeted=%d enriched=%d failed=%d",
            img_m.targeted, img_m.enriched, img_m.failed,
        )
        result["image_enrich_movable"] = {
            "targeted": img_m.targeted,
            "enriched": img_m.enriched,
            "failed": img_m.failed,
        }

    # 6) 입찰정보 (#7)
    if settings.SCHEDULER_BID_INFO_LIMIT > 0:
        logger.info(
            "Bid info enrich start (limit=%d).", settings.SCHEDULER_BID_INFO_LIMIT,
        )
        bi = await service.enrich_bid_info(limit=settings.SCHEDULER_BID_INFO_LIMIT)
        logger.info(
            "Bid info enrich done — targeted=%d enriched=%d failed=%d",
            bi.targeted, bi.enriched, bi.failed,
        )
        result["bid_info"] = {
            "targeted": bi.targeted, "enriched": bi.enriched, "failed": bi.failed,
        }

    return result
