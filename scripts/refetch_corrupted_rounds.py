"""누락 회차 보강 — Phase A(pbanc 매핑 해결) → Phase B(회차 enrich) 순차 실행.

배경:
  OnBid 한 매물(cltrMngNo)에 여러 회차(pbctCdtnNo)가 존재하지만, ingest 시점에
  `getRlstCltrList2`가 임박 회차만 보여줘서 누락된 회차가 다수 있다.
  예) cltrMngNo=2024-05650-001
      1회차 pbct=5980140 (2026-07-08 마감, 19.9억) — DB 누락
      7회차 pbct=5979842 (2026-08-19 마감, 7.96억) — DB 존재

복구 흐름:
  Phase A — `pbanc_mng_no`가 NULL인 active 매물에 대해 `getPbancList2`로 매핑 해결.
  Phase B — 해결된 공고 단위로 `getPbancCltrInf2` 호출 → DB에 없는 (cltr, pbct) 회차 INSERT.

두 페이즈는 기존 `OnbidIngestService` 메서드를 그대로 재사용.

사용 예:
  python -m scripts.refetch_corrupted_rounds                           # 기본 한도로 두 페이즈
  python -m scripts.refetch_corrupted_rounds --limit-a 500 --limit-b 200
  python -m scripts.refetch_corrupted_rounds --skip-phase-a            # B만
  python -m scripts.refetch_corrupted_rounds --env .env                # 로컬 .env로
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# DB/서비스 import 전에 dotenv 로드 — `--env` argv를 사전 파싱.
_pre = argparse.ArgumentParser(add_help=False)
_pre.add_argument("--env", default=".env.production")
_pre_args, _ = _pre.parse_known_args()
load_dotenv(_pre_args.env)
if not os.getenv("ONBID_SERVICE_KEY"):
    load_dotenv(".env")

from app.api.deps import get_auction_repository  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.infrastructure.external.kakao_geocoder import KakaoGeocoder  # noqa: E402
from app.infrastructure.external.onbid_client import OnbidClient  # noqa: E402
from app.services.onbid_ingest_service import OnbidIngestService  # noqa: E402

logger = logging.getLogger("refetch_corrupted_rounds")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limit-a",
        type=int,
        default=500,
        help="Phase A (pbanc_mng_no 해결) 대상 row 수 (default: 500).",
    )
    parser.add_argument(
        "--limit-b",
        type=int,
        default=200,
        help="Phase B (누락 회차 enrich) 공고 그룹 수 (default: 200).",
    )
    parser.add_argument(
        "--skip-phase-a",
        action="store_true",
        help="Phase A 건너뛰기 (이미 해결되어 있다면).",
    )
    parser.add_argument(
        "--skip-phase-b",
        action="store_true",
        help="Phase B 건너뛰기 (Phase A 결과만 확인).",
    )
    parser.add_argument(
        "--loop",
        type=int,
        default=1,
        help="두 페이즈를 N회 반복 (default: 1). OnBid 일 쿼터 1000 주의.",
    )
    parser.add_argument(
        "--env",
        default=".env.production",
        help="dotenv 파일 (default: .env.production)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    settings = get_settings()
    if not settings.ONBID_SERVICE_KEY:
        print("ONBID_SERVICE_KEY not set", file=sys.stderr)
        return 1

    repo = get_auction_repository()
    client = OnbidClient(service_key=settings.ONBID_SERVICE_KEY)
    geocoder = KakaoGeocoder(rest_api_key=settings.KAKAO_REST_API_KEY)
    service = OnbidIngestService(
        client=client, geocoder=geocoder, repo=repo,
        geocode_concurrency=settings.GEOCODE_CONCURRENCY,
    )

    total_a = {"targeted": 0, "resolved": 0, "failed": 0, "api_calls": 0}
    total_b = {"targeted": 0, "enriched": 0, "failed": 0, "api_calls": 0}

    for loop_i in range(1, args.loop + 1):
        if args.loop > 1:
            logger.info("===== loop %d/%d =====", loop_i, args.loop)

        if not args.skip_phase_a:
            logger.info("Phase A — pbanc_mng_no resolve (limit=%d) 시작", args.limit_a)
            pa = await service.enrich_pbanc_mng_no(limit=args.limit_a)
            logger.info(
                "Phase A 완료 — targeted=%d resolved=%d failed=%d api_calls=%d",
                pa.targeted, pa.enriched, pa.failed, pa.api_calls,
            )
            total_a["targeted"] += pa.targeted
            total_a["resolved"] += pa.enriched
            total_a["failed"] += pa.failed
            total_a["api_calls"] += pa.api_calls
            if pa.targeted == 0:
                logger.info("Phase A 후보 없음 — Phase A 종료")
                args.skip_phase_a = True

        if not args.skip_phase_b:
            logger.info("Phase B — missing rounds enrich (limit=%d) 시작", args.limit_b)
            pb = await service.enrich_missing_rounds_via_pbanc(limit=args.limit_b)
            logger.info(
                "Phase B 완료 — targeted=%d enriched=%d failed=%d api_calls=%d",
                pb.targeted, pb.enriched, pb.failed, pb.api_calls,
            )
            total_b["targeted"] += pb.targeted
            total_b["enriched"] += pb.enriched
            total_b["failed"] += pb.failed
            total_b["api_calls"] += pb.api_calls
            if pb.targeted == 0:
                logger.info("Phase B 대상 그룹 없음 — Phase B 종료")
                break

        if args.skip_phase_a and args.skip_phase_b:
            break

    print("\n=== summary ===")
    print(f"Phase A: {total_a}")
    print(f"Phase B: {total_b}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
