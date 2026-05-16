"""기존 매물 좌표 백필 — 동(洞) centroid에 뭉친 row를 parcel 단위로 재지오코딩.

배경:
    fix/geocoding-parcel-level 이전에 수집된 row는 address가 동까지만
    합성되어 KakaoGeocoder가 동 centroid를 반환 → 같은 동 매물 다수가
    한 점에 누적(전체 89% 중복). 본 스크립트는 동일 location에 누적된
    row들을 식별해, 새 ingest와 동일한 로직(`compose_address` + title
    지번 추출 + parcel 응답 검증)으로 재지오코딩한다.

동작:
    1. DB에서 `location IS NOT NULL`이고 같은 location에 `--min-cluster`
       이상이 누적된 row를 LIMIT만큼 가져옴.
    2. 각 row를 `compose_address(region_*, title=title)`로 재합성.
    3. KakaoGeocoder.lookup — parcel-level이 아니면 (None, None) 반환.
    4. dry-run이 아니면 auctions.address/location 갱신.
       좌표가 새로 안 나오면 location=NULL로 정정(가짜 좌표 잔존 방지).

사용:
    .env에 KAKAO_REST_API_KEY, DATABASE_URL 설정 후
    python -m scripts.backfill_geocoding --dry-run --limit 50
    python -m scripts.backfill_geocoding --limit 2000 --concurrency 10

쿼터:
    Kakao Local API 일 30만 호출 한도. 14k rows 처리에도 여유.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv  # noqa: E402
from sqlalchemy import func, select, update  # noqa: E402

logger = logging.getLogger("backfill_geocoding")


@dataclass(slots=True)
class Stats:
    targeted: int = 0
    api_calls: int = 0
    updated: int = 0
    nullified: int = 0
    skipped_no_address: int = 0
    failed: int = 0


async def _fetch_targets(session_factory, *, min_cluster: int, limit: int):
    """동일 location에 min_cluster 이상 누적된 매물 — (id, title, address, region_*)."""
    from app.infrastructure.db.models import AuctionORM

    async with session_factory() as session:
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
    return rows


async def _update_row(
    session_factory, auction_id: int, address: str, lng: float | None, lat: float | None,
) -> None:
    from app.infrastructure.db.models import AuctionORM

    async with session_factory() as session:
        values: dict = {"address": address}
        if lng is not None and lat is not None:
            values["location"] = func.ST_SetSRID(func.ST_MakePoint(lng, lat), 4326)
        else:
            values["location"] = None
        await session.execute(
            update(AuctionORM).where(AuctionORM.id == auction_id).values(**values)
        )
        await session.commit()


async def _process_one(
    row, *, geocoder, session_factory, dry_run: bool, sem: asyncio.Semaphore, stats: Stats,
) -> None:
    from app.services.onbid_ingest_service import compose_address

    new_addr = compose_address(
        row.region_sido, row.region_sigungu, row.region_emd, title=row.title,
    )
    if not new_addr:
        stats.skipped_no_address += 1
        return

    async with sem:
        stats.api_calls += 1
        lng, lat = await geocoder.lookup(new_addr)

    verb = "(dry)" if dry_run else ""
    logger.info(
        "id=%-6d addr=%r → (%s, %s) %s",
        row.id, new_addr, lng, lat, verb,
    )
    if dry_run:
        return

    try:
        await _update_row(session_factory, row.id, new_addr, lng, lat)
    except Exception as e:  # noqa: BLE001
        logger.warning("update failed id=%d: %s", row.id, e)
        stats.failed += 1
        return

    if lng is None or lat is None:
        stats.nullified += 1
    else:
        stats.updated += 1


async def run(args) -> int:
    from app.core.config import get_settings
    from app.core.database import AsyncSessionLocal
    from app.infrastructure.external.kakao_geocoder import KakaoGeocoder

    settings = get_settings()
    if not settings.KAKAO_REST_API_KEY:
        print("KAKAO_REST_API_KEY not configured", file=sys.stderr)
        return 1

    geocoder = KakaoGeocoder(rest_api_key=settings.KAKAO_REST_API_KEY)
    rows = await _fetch_targets(
        AsyncSessionLocal, min_cluster=args.min_cluster, limit=args.limit,
    )
    stats = Stats(targeted=len(rows))
    logger.info(
        "Backfill start — targeted=%d min_cluster=%d concurrency=%d dry_run=%s",
        stats.targeted, args.min_cluster, args.concurrency, args.dry_run,
    )
    if not rows:
        return 0

    sem = asyncio.Semaphore(args.concurrency)
    await asyncio.gather(*[
        _process_one(
            r, geocoder=geocoder, session_factory=AsyncSessionLocal,
            dry_run=args.dry_run, sem=sem, stats=stats,
        )
        for r in rows
    ])

    logger.info(
        "Backfill done — targeted=%d api_calls=%d updated=%d nullified=%d "
        "skipped_no_address=%d failed=%d",
        stats.targeted, stats.api_calls, stats.updated, stats.nullified,
        stats.skipped_no_address, stats.failed,
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="auctions 좌표 백필.")
    parser.add_argument("--limit", type=int, default=2000,
                        help="처리할 최대 row 수 (기본 2000). 여러 번 나눠 실행 권장.")
    parser.add_argument("--min-cluster", type=int, default=2,
                        help="이 수 이상 누적된 location만 백필 대상 (기본 2).")
    parser.add_argument("--concurrency", type=int, default=10,
                        help="카카오 API 동시 호출 수 (기본 10).")
    parser.add_argument("--dry-run", action="store_true",
                        help="DB 갱신 없이 결과만 출력.")
    parser.add_argument("--env-file", default=".env",
                        help="환경변수 파일 (기본 .env).")
    parser.add_argument("--log-level", default="INFO",
                        choices=("DEBUG", "INFO", "WARNING", "ERROR"))
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    )
    load_dotenv(args.env_file)

    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
